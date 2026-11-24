# Telnet / ulogio：A7C II のほうが条件が良い

## 1. 実装が残っている

A7 IV では 6.02 の `libosal_ulogio.so` から telnet 生成コードが削られており、
公開手法は旧 1.05 の p15 から移植していた。
**A7C II 2.01 にはその移植が要らない。**

`lib/libosal_ulogio.so`（40,168 バイト）から確認できるシンボルと文字列：

```text
ulogio_telnetd_init            (VA 0x50b4)
ulogio_telnetd_mainloop        (VA 0x4684)
ulogio_telnetd_exit            (VA 0x527c)
ulogio_telnetd_print_termlist
ulogio_telnetd_select_io_term_by_index / _by_id
ulogio_filter_get_telnet / ulogio_filter_set_telnet
ulogio_filter_print_telnetinfo
"[ulogio] accept() failed "
"[ulogio] failed to created telnet sessions "
"telnet flag update, now the flag = %s "
```

`ulogio_telnetd_init` の VA `0x50b4` は、A7 IV 6.02 で公開されている
パッチ対象 VA のひとつと同じ。`.init_array` の VA も `0x18d18` で一致しており、
ELF の作りが同系であることを裏づける。

## 2. CLI 側にスイッチがある

`bin/ulogio.elf` のヘルプ文字列：

```text
term on  -- enable terminal output
term off -- disable terminal output
telnet up   -- enable telnet output, must be reboot system
telnet down -- disable telnet output, must be reboot system
tlist / ot / it / rewind -- 端末の一覧と入出力先の選択
```

工場側の使い方の痕跡として `wifi-scripts/ulset.sh` が残っており、
`ulogio filter on <subsys> INFO` を並べてネットワーク系サブシステムの
ログを開けている。

つまり**シェルが1回でも取れれば `ulogio telnet up` → 再起動で TCP 23 が開く**
という順序。逆に言えば、telnet 自体はシェルを取る手段ではなく、
取った後に恒久化する手段として最も安い。

## 3. フラグの永続化先：`/setting/ulogio.bin`（確定）

ulogio はカーネルモジュール `kmod/osal_ulogio.ko` が本体で、
ユーザー空間の `libosal_ulogio.so` は同じフィルタ設定パーサを持つ複製。
モジュールはフィルタ設定ファイルのパスを **insmod のモジュールパラメータ**で
受け取る。p3 initrd の `sbin/initrc/insmod_drv2` にその行がある：

```sh
insmod /usr/kmod/osal_ulogio.ko ulogio_initfile=/setting/ulogio.bin \
    ulogio_cp_filterfile=/cp/filter.bin
```

| パス | 実体 | 役割 |
| --- | --- | --- |
| `/setting/ulogio.bin` | `/dev/nflasha2` vfat rw | フィルタ設定（**telnet フラグを含む**） |
| `/cp/filter.bin` | `/dev/nflasha8` vfat rw | コプロセッサ側のフィルタ |

どちらも**不揮発**。つまり `ulogio telnet up` が「再起動が必要」と言うのは、
フラグをこのファイルに書き、次の insmod で読み直させるため。

**バックアップ（BK4）経由ではない。** モジュールは確かに `Backup_read` /
`Backup_get_datasize` を import しているが、呼び出し箇所を追うと使っている ID は

| BK ID | サイズ | 使う関数 | 用途 |
| --- | --- | --- | --- |
| `0x00fa0132` | 4 | `ulogio_get_logaddr` | ログバッファのアドレス |
| `0x00fa006e` | 8 | `ulogio_debug_display_add` | デバッグ表示 |

の2件だけで、フィルタ設定（`TELN`）は含まれない。
**したがって `bk w` だけで telnet を上げることはできない**（前回の仮説は否定された）。
必要なのは `/setting/ulogio.bin` への**ファイル書き込み**で、それには
シェルか Jiritsu の `SET_FILE`（＝サービス権限レベル A）が要る。

なお、モジュールは `proc_create_data` で **`/proc/osal/ulogio`** を作り、
`filterfile : %s` や `Backup API error count : %d` を表示する。
シェルが取れたなら、現在のフィルタとファイルパスはここで確認できる。

## 3a. ファイル形式（確定）

`ulogio_filter_load_setting`（lib VA `0x6010`）は、ファイル全体を
**レコードの並び**として読む。各レコードは先頭から：

| オフセット | 型 | 内容 |
| --- | --- | --- |
| +0 | u32 | このレコードの長さ（固定長レコードは 12） |
| +4 | u32 | タグ。ASCII 4文字がファイル上はリトルエンディアン |
| +8 | u32… | 値 |

カーソルは「レコード先頭 + 長さ」へ進む。認識されるタグと、
`ulogio_filter_save_setting`（VA `0x6364`）が書く順序：

| 順 | タグ | 内容 |
| --- | --- | --- |
| 1 | `DBGL` | デバッグレベル |
| 2 | `FLTA` | abort フラグ |
| 3 | `TERM` | 端末出力 |
| 4 | `EFRE` | efree フラグ |
| 5 | `TTAG` | タイムタグ種別 |
| 6 | **`TELN`** | **telnet listener の有効フラグ** |
| 7 | `PROX` | proxy（u32） |
| 8 | `SFLT` | サブシステムフィルタ：u32 件数 + 件数分の u32 |
| 9 | `CFLT` | コンポーネントフィルタ：u32 件数 + 件数分の u64 |

`FVER` レコードも読み側は受け付け、値が `0x10` でなければ
「unknown version of filter setting」で拒否する。ただし
**保存側は `FVER` を書かない**（読み側がタグ無しを許すため）。

つまり telnet を上げるだけなら、**12バイトのファイル1つで足りる**：

```
0c 00 00 00  54 45 4c 4e  01 00 00 00
   len=12       "TELN"        value=1
```

生成と確認は `scripts/ulogio_filter_file.py`：

```bash
python3 scripts/ulogio_filter_file.py --telnet 1 -o /tmp/ulogio.bin
python3 scripts/ulogio_filter_file.py --parse /tmp/ulogio.bin
```

既存の `/setting/ulogio.bin` がある機体では、**まず現物を読んで保管し**、
その内容に `TELN` を足した形に作り直すこと。丸ごと置き換えると
他のフィルタ設定が消える。

## 4. 残る前提

- telnetd が上がっても、到達には IP 経路（Wi-Fi 接続か USB ネットワーク）が必要。
- `ulogio` のログイン無し・平文という性質上、**有効にしたまま公衆無線に
  つながない**。検証は閉じたネットワークで行う。
- 端末が開いただけ（TCP ハンドシェイクや marker だけ）では成功と見なさない。
  実際にコマンドが返り、UID/GID が 0 であることを確認する。
