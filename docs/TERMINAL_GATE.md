# 端末ゲートの正体（静的解析、2026-11-24）

> **結論（2026-11-24、実機）：このゲートは閉じていなかった。**
> 実行中の `libsencore.so` では TERM_MODE のフラグバイトが**既に `0x00`**
> （ファイル上は `0x80`）で、`terminal_change_function_is_disabled` も `0x00`。
> つまり**フラグ仮説は外れ**で、`shell` が通らない原因は別にある。
> 実測値：
>
> ```text
> libsencore.so base: 0x007f94dbd000
> record at +0x2782c: 0x5f 0x02 0x3d 0x00 0x01 0x06 0x1f 0x00
> terminal_change_function_is_disabled (+0x6d9a0): 0x00
> ```
>
> 何かが実行時にこのフラグを下げている（レベル A の初期化と見られる）。
> `jit_termgate` は署名照合で `0x80` を期待していたため、**何も書かずに中止した**。
>
> **端末はもう必要ない。** root でコードが走るので、Jiritsu のファイル経路を
> コマンドチャネルにした（`native/jit/jit_sh.c`）。

`shell` が「`Terminal activated.` は出るのに入力が届かない」件を、
ファームウェア側から追った結果。**実機では未検証。**

## 1. PMCA の「端末有効化」は2段あって、1段目は何もしていない

`pmca/usb/sony.py` の `setTerminalEnable()` はこうなっている：

```python
self._sendProductInfoPacket(*self.SONY_PRODUCT_INFO_TERM_CHANGE, dump8(1 if enable else 0))
try:
    self._sendAdjustControlPacket(*self.SONY_ADJUST_SENSER_TERM_MODE, dump8(2 if enable else 0))
except:
    pass
```

### 1段目：ProductInfo `0x00f1`（TERM_CHANGE）＝ **no-op**

`ProductInfoFunc` はコマンドをプラグイン `libpro%02X.so` に振る。
`0x00f1` の上位バイトは `0x00` なので **`lib/libpro00.so`**（6,032 バイト）。
その中身を IDA でデコンパイルすると：

```c
__int64 command00F1()
{
  return 1;          // 成功を返すだけ。何もしない
}
```

比較のため、同じモジュールの `command001F`（READ_HASP）は
`Read_Hasp()` / `Reset_Hasp()` を呼び、失敗時に 129 / 130 を返す実装になっている。
**`command00F1` は中身が無い。**

### 2段目：AdjustControl `0x601/0x1f`（TERM_MODE）＝ 失敗が揉み消される

PMCA はこれを `try/except: pass` で囲んでいる。つまり

- **`Terminal activated.` の表示は、何の保証でもない**
- 実際の有効化は2段目だけが担っていて、その失敗は表に出ない

fork が観測した「有効化は通るのに入力が届かない」は、この構造と完全に整合する。

## 2. TERM_MODE はフラグバイトで塞がれている

`libsencore.so` には AdjustControl のコマンド記述表がある。
**0x48 バイト固定のレコードが21件**、ファイルオフセット `0x2770c` から
（同じ表の複製が `0x47714` にもある）。レコードの形：

| オフセット | 型 | 内容 |
| --- | --- | --- |
| +0 | u32 | `0x003d025f` ＝ 処理する OSAL サブシステム id（`sens_adjCmd_init` が
この id でメッセージキューのコールバックを登録している） |
| +4 | u16 | カテゴリ |
| +6 | u8 | コマンド |
| **+7** | **u8** | **フラグ** |
| +8.. | char[] | 名前 |

全21件：

| カテゴリ | コマンド | フラグ | 名前 |
| --- | --- | --- | --- |
| `0x0601` | `0x12` | `0x00` | FCT_MODE |
| `0x0601` | `0x13` | `0x80` | DBG_MODE |
| `0x0601` | `0x14` | `0x40` | TST_MODE |
| `0x0601` | `0x1a` | `0x00` | SELECT_LSI |
| `0x0601` | **`0x1f`** | **`0x80`** | **TERM_MODE** |
| `0x0601` | `0x21` | `0x00` | GPIO_READ |
| `0x0601` | `0x22` | `0x00` | TIMER |
| `0x0601` | `0x23` | `0x40` | GET_LOG |
| `0x0601` | `0x2f` | `0x40` | HASP |
| `0x0601` | `0x31` / `0x32` | `0x00` | SSBI_MK_MODE / READ_SSBI |
| `0x0601` | `0x41` | `0x00` | READ_NFLASHA8 |
| `0x0601` | `0x51` / `0x52` / `0x53` | `0x00` | ILOG_WRITE / ILOG_READ / ILOG_DEL |
| `0x0601` | `0x61` / `0x62` | `0x40` | XPWR_OFF_DISABLE_PORT_INFO / _SET |
| `0x0601` | `0xa0` | `0x88` | ETOOLS_SENSER_SAMPLE |
| `0x0601` | **`0xfe`** | **`0x00`** | **RAM_READ** |
| `0x0601` | **`0xff`** | **`0x40`** | **RAM_WRITE** |
| `0x0603` | `0x01` | `0x00` | READ（バックアップ読み取り。`bk r` が使っていて**動く**） |

**A7 IV の公開パッチと一致する。** Erlla/sony-a7m4-custom-firmware の
`reference-layout.json` にある `normal_sencore` の
`term_mode_patch`（ファイルオフセット `0x26e13`、`80` → `00`）は、
**彼らのビルドにおける同じフィールド**＝ TERM_MODE レコードのフラグバイト。
つまり「フラグ `0x80` が TERM_MODE を塞いでいて、`0x00` にすると通る」ことは
A7 IV 側で実証済み。

A7C II 2.01 における同じバイトは **`libsencore.so` のファイルオフセット `0x27833`**
（複製側は `0x4783b`）。

フラグの意味そのものはコードから未確認（記述表を読む側のコードが
テーブル基底アドレスを直接参照しておらず、まだ追えていない）。
`0x00` のコマンドが実際に動いている（`0x603/0x01` READ、`bk r`）ことと、
A7 IV の実証から、**`0x80` が拒否条件**という読みは十分強い。

## 3. 同じカテゴリに RAM_READ / RAM_WRITE がある

| コマンド | フラグ | 名前 | 意味 |
| --- | --- | --- | --- |
| `0x0601/0xfe` | `0x00` | RAM_READ | フラグは**動くコマンドと同じ値** |
| `0x0601/0xff` | `0x40` | RAM_WRITE | `0x40` は TST_MODE / GET_LOG / HASP と同じ |

これが効くなら、**フラグバイトを RAM 上で `0x00` に書き換えて端末を開ける**
可能性がある。`libsencore.so` の `.rodata` は読み取り専用マウントの p15 由来だが、
**プロセスにロードされた後のページを書けば不揮発には何も残らない**。
RAM_READ はフラグ `0x00` なので、**まず読み取りだけで試せる**。

引数の形式は未確認。**RAM_WRITE は番号を間違えれば即座に実害が出る**ので、
RAM_READ で形式を確定させてからでなければ触らない。

## 3a. 我々のコードは同じプロセスにいる（2026-11-24）

`jit_probe` の報告で、ライブラリが読み込まれるのは
**`/usr/bin/im.elf`（pid 532、uid 0、全ケーパビリティ）**だと分かった。
サービスプロトコルを処理しているのも同じプロセスなので、
**`libsencore.so` の `.data` は我々と同じアドレス空間にある。**

つまり `terminal_change_function_is_disabled`（ファイルオフセット `0x27833`
に対応するランタイムの1バイト）は、**RAM_WRITE コマンドを使わず、
ライブラリの中から直接書き換えられる**。
`/proc/self/maps` で `libsencore.so` のベースを読み、
`base + 0x27833` に `0x00` を書けばよい（`.data` は書き込み可能なので
`mprotect` も不要な見込み）。

そして**コンソール側の相手も確認できた**：pid 528 で `/bin/ash --` が
待機している。端末が開けばこれに繋がる。

これは**不揮発には何も書かない**（プロセスのメモリだけ）。電源を切れば元に戻る。

## 4. 次の順番（安全な順）

1. **RAM_READ（`0x601/0xfe`）が応答するか**を確かめる。読み取りのみ。
   既知の値が入っている物理アドレス（例：`libsencore.so` の `.rodata` が
   載っているページ）を読み、ファイル内容と一致するかで引数形式を確定する
2. 一致したら、`0x27833` 相当のランタイムアドレスを特定する
   （`libsencore.so` のロードアドレス ＋ `0x27833`。読み取りで照合できる）
3. RAM_WRITE でそのバイトを `0x00` にする（**1バイトだけ**）
4. `setTerminalEnable` をやり直して `shell` を試す
5. 電源を切れば元に戻る（p15 は読み取り専用なので、書いたのは RAM だけ）

経路が無ければ、残るのは p15 の書き換え（恒久）になる。

---

## 追記（端末側担当・独立検証と2つの訂正、2026-11-24）

上の表とフラグバイトは**独立に検証した**。
`0x2770c` から 0x48 バイト × 21 レコード、`TERM_MODE` のフラグは
`0x27833 = 0x80`、複製は `0x4783b`。記述どおり。

その上で、**次の一手の組み立てに影響する差が2つ**ある。

### 訂正1：Senser ブロックの `RAM_WRITE` はフラグ `0x40`。**使うべきは別カテゴリ**

`RAM_READ` / `RAM_WRITE` は Senser（`0x0601`）だけのものではない。
同じ 0x48 バイト形式のレコードを全文から拾うと、**複数のサブシステムが
それぞれのカテゴリで同じ 0xfe / 0xff を持っている**：

| カテゴリ | サブシステム | RAM_READ (0xfe) | RAM_WRITE (0xff) |
| --- | --- | --- | --- |
| `0x0601` | `0x003d025f` | flags **0x00** | flags **0x40** |
| **`0x0421`** | `0x901501f4` | flags **0x00** | flags **0x00** |
| `0x0404` | `0x900301d7` | 0x00 | 0x00 |
| `0x0405` | `0x900301d7` / `0x90b501a3` | 0x00 | 0x00 |
| `0x040f` | `0x900601ec` / `0x901701f3` | 0x00 | 0x00 |
| `0x0415` | `0x901701f3` / `0x900f01f9` | 0x00 | 0x00 |
| `0x0418` | `0x900f01f9` / `0x900d01fc` | 0x00 | 0x00 |
| `0x0d21` | `0x901504bf` | 0x00 | 0x00 |
| `0x0304` | `0x80570254` | flags 0x40 | — |

「フラグ `0x00` なら通る」という仮説に乗るなら、**`0x0601/0xff`（0x40）ではなく
`0x0421/0xff`（0x00）を使うべき**。`0x0601` の書き込みだけがわざわざ
`0x40` になっているので、そこを選ぶ理由がない。

### `0x0421` を推す理由がもう1つある

`SubsystemCommunicationCommand::TransactionStart` は **PFUNC `0xff03`
（MemoryDump）をサブシステムコマンド `0x421` に変換**している
（`libsencore.so` の `0xfc44` 付近、`cmp w1, #0xff03` → `mov w0, #0x421`）。

PMCA 側の `MemoryDump` のヘッダは `{u32 base, u32 size}`：

```python
MemoryDumpHeader = Struct('MemoryDumpHeader', [('base', INT32), ('size', INT32)])
def readMemory(self, base, size, outFile=None): ...
def writeMemory(self, base, data): ...
```

つまり **`0x0421` の `RAM_READ` / `RAM_WRITE` は、PMCA が `bootrom` で
使っている経路そのもの**で、引数形式の第一候補がすでに分かっている。
`0xff03` はどのレベルのテーブルにも無いので USB 前面からは届かないが、
**`0x40` AdjustControl でカテゴリ `0x0421` を直接叩けば同じ場所に届く**。

### 訂正2：`GET_LOG`（`0x601/0x23`）は**ログを消す**

`sub_11B50`（`0x11b50`）が `GET_LOG` のハンドラで、`/proc/klog` /
`/proc/snsc_boot_time` / `/proc/osal/uipc` を扱う。だが**セレクタ `0xff` の
分岐は9件のファイルを削除する**：

```c
if ( v2 == 255 ) {
    do {
      v9 = off_6C568[v7];
      if ( sub_10A98(4, nullptr, v9) != 0 )     // delete
        snprintf(s, 0xFFu, "failed to delete %s", v9);
      ++v7;
    } while ( v7 != 9 );
```

「フラグ `0x40` が通るかどうかの試金石に `GET_LOG` を使う」のは**避ける**。
読み取り専用で `0x40` を試したいなら `0x601/0x61`
`XPWR_OFF_DISABLE_PORT_INFO`（名前のとおり INFO、`_SET` は `0x62` と別）が妥当。

## こちらの次の一手（読み取りのみ）

`scripts/ram_read_probe.py` を用意した。**`RAM_READ`（0xfe）しか送らない。**

- カテゴリ `0x0421` → `0x0601` の順に試す
- 引数形式は `{u32 base, u32 size}` から、前置ヘッダ 1 / 3 バイト版も順に
- 対象は **ブート ROM `0xffff0000`**（PMCA の `bootrom` が読む既知領域）を
  `0x40` バイトだけ。同じ読みを2回して一致するかで形式を確定する

形式が固まるまで `RAM_WRITE` は送らない。固まった後も、書くのは
**検証済みアドレスの1バイトだけ**にする。
