# 端末ゲートの正体（静的解析、2026-11-24）

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
