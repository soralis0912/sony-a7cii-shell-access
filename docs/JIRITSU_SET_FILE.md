# Jiritsu `SET_FILE`：ネイティブコード実行の経路（2026-11-24、静的解析）

USB 端末が死んでいる（[CAMERA_FACTS.md](CAMERA_FACTS.md)）一方で、
**こちらは実機で通っている輸送路の上にある**。Jiritsu のカテゴリ `0x1001` は
`0x40` AdjustControl 経由で、読み取りは 2026-11-24 に実機で成功している。

実装は `lib/libJiritsu.so`。コマンド1件が1関数で、名前がそのまま残っている
（`adj_cmd_set_file` @ `0x9038`、`adj_cmd_set_file_path` @ `0x8cf8`、
`adj_cmd_get_file2` @ `0xa1b8` ほか）。以下は IDA の Hex-Rays 出力から。

## 核心：`libJit.so` を置くと `dlopen` される

`adj_cmd_set_file` の末尾：

```c
v2 = write(v14, v17, v9);
fsync(v15); close(v15);
...
if ( strcmp(v8, "/tmp/jiritsu/libJit.so") == 0 ) {
    dlopen("/tmp/jiritsu/libJit.so", 1);   // ← サービスプロセス内で実行
    dlclose(v18);
}
```

つまり **書き込んだファイルが `libJit.so` のときだけ、サービスが自分で
`dlopen` する**。共有ライブラリの初期化（コンストラクタ／`.init_array`）は
その時点で走るので、**認証済みサービスプロセスの権限でネイティブコードが
実行される**。A7 IV の研究が「一時 `libJit.so` をサービスプロセスに
読み込ませる」と書いているのは、この同じ仕組みのこと。

## 書き込み先はパスではなく「番号で選ぶ固定表」

`adj_cmd_set_file` は**リクエストのパスを使わない**。
`get_jiritsu_area_filename(request[41])` が返す名前に書く。

| 番号 | ファイル | 備考 |
| --- | --- | --- |
| 0 | `/tmp/jiritsu/tmmc.jit` | |
| 1 | `/tmp/jiritsu/DIAC.csv` | |
| **2** | **`/tmp/jiritsu/libJit.so`** | **書くと `dlopen` される** |
| 3 | `/tmp/jiritsu/jit.log` | `set_file` が明示的に拒否 |
| 4 | `/tmp/jiritsu/history.txt` | 同じく拒否 |
| その他 | `unk_47AD8` の34件の表（16バイト×34） | 未展開 |

**任意パスへは書けない。** `../../` が効くのは読み取り側
（`adj_cmd_set_file_path`、文字検証つき、最大 0x201 バイト）だけ。
つまり `/etc/ssh/sshd_config` を直接書く、という手は**使えない**。
`libJit.so` 経由でコードを走らせ、その中から書くことになる。

## リクエストの形

ペイロードの先頭3バイトがヘッダで、ハンドラ側の構造体 `a1+40/41/42` に
対応する。対応関係は `adj_cmd_get_file2` で裏が取れる：実機で成功した
プローブは `\x00\xff\x00` を送っており、ハンドラは `*(a1+40)` を最初に見て
`0` なら「`SET_FILE_PATH` で設定済みのパスを読む」分岐に入る。

```text
カテゴリ 0x1001 / コマンド 0x4007 (SET_FILE)
  payload[0]  = 0x00     ; a1+40。0 以外はエラー 513
  payload[1]  = 0x02     ; a1+41。ファイル番号（2 = libJit.so）
  payload[2]  = 0x00     ; a1+42。0 = そのまま書く / 1 = libCommuTalk を通す
  payload[3:] = ファイルの中身
```

比較：

```text
0x400f SET_FILE_PATH : payload[0]=0x00, payload[1:] = パス文字列（読み取り用）
0x4011 GET_FILE2     : payload = 00 ff 00（実機で成功）
```

## 前提と制約

| 項目 | 内容 |
| --- | --- |
| マウント | ハンドラが毎回 `/dev/nflasha6` を `/tmp/jiritsu` に **vfat** でマウントする（`sys_mount`） |
| ロック | `libJit.so` を書くときは **`/tmp/jbusy` が存在しないこと**。`sys_file_chk_exist` は「存在する＝0」を返し、`0` ならエラー 17 で中断 |
| 容量 | `/tmp/jiritsu/*` の合計が **26,214,400 バイト（25 MiB）**未満。超えるとエラー 15 |
| サイズ | `payload` 全体から3バイト引いた値が書き込みサイズ |
| 失敗コード | 8 = open 失敗、9 = write 失敗、15 = 容量超過、17 = `/tmp/jbusy`、21 = dmm 確保失敗、513 = パラメータ不正 |

## 危険の所在

- **同じカテゴリに `0x4003 FORMAT` と `0x4006 FIRMUP` と
  `0x4009 FILE_DELETE` が並んでいる。** コマンド番号を1つ間違えると
  実験ではなく事故になる。送る前に番号を2回読むこと。
- `dlopen` された `.so` は**サービスプロセス内で走る**。無限ループや
  クラッシュはサービスを巻き込む。最初に試すものは、**何か1行ログを出すか
  小さなファイルを1つ書くだけ**にとどめ、戻り値を返して終わること。
- 書き込み先は p6（`/dev/nflasha6`）の vfat で、**撮影データや調整値の
  パーティションではない**。とはいえ `FORMAT` を誤爆すればそこを消す。

## 次にやること

1. 【PC】`unk_47AD8` の34件の表を展開し、残りのファイル名を確認する。
2. 【PC】最小の `libJit.so` を作る。aarch64 向け共有ライブラリで、
   コンストラクタで `/tmp/jiritsu/` に短いファイルを1つ書くだけのもの。
   クロスツールチェインが必要。
3. 【実機】`SET_FILE` を**番号2・モード0**で送り、戻り値を確認する。
4. 【実機】`SET_FILE_PATH` + `GET_FILE2` で、置いたファイルが
   書かれていること（＝コンストラクタが走ったこと）を読み戻して確かめる。
5. 通れば、その中から `/etc/ssh/sshd_config` と `/etc/passwd` を書き換える
   （[SSH.md](SSH.md)、[CAMERA_FACTS.md](CAMERA_FACTS.md)）。
