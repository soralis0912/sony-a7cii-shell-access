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

## 3. フラグの永続化先（未確定）

`ulogio_filter_load_setting`（VA `0x6010`）は 4文字タグの TLV を順に読む。
逆アセンブルから読めたタグは `TERM`、`TELN`、`TTAG`、`DBGL`、`CFLT`、
`FLAT`、`FERE`、`FCHK`、`FREV` 系で、`TELN` が telnet フラグに対応する。

設定の入口は2つある：

- `ulogio_filter_load_setting_f`（VA `0x62e4`）＝ファイルから。
  ファイル名は呼び出し側が与える（`ulogio_get_filterfile` は `.data` の
  `0x19ad8` のポインタを返すだけで、このライブラリ内に literal は無い）。
  失敗時の文字列は `[ulogio] cannot save filter setting to %s`。
- `ulogio_read_backup(bkid, buf, size)`（VA `0x7428`）＝BK4 バックアップから。
  `Backup_get_datasize` と `Backup_read` を外部シンボルとして取り込んでいる。
  現在確認できている呼び出しは**ログ退避（`/log/cp/*.bin`、`/log/escapelog.bin`）
  側**で、`TELN` を含むフィルタ設定そのものがバックアップ由来かは未確定。

ここが確定すれば、「`bk w` だけで telnet を上げられるか」が決まる。
**もし TELN がバックアップ由来なら、ファームウェアを一切書き換えずに
telnet root 端末が成立する可能性がある**ので、優先度は最も高い。
確定作業は静的解析だけで足りる（[TODO.md](../TODO.md) の A）。

## 4. 残る前提

- telnetd が上がっても、到達には IP 経路（Wi-Fi 接続か USB ネットワーク）が必要。
- `ulogio` のログイン無し・平文という性質上、**有効にしたまま公衆無線に
  つながない**。検証は閉じたネットワークで行う。
- 端末が開いただけ（TCP ハンドシェイクや marker だけ）では成功と見なさない。
  実際にコマンドが返り、UID/GID が 0 であることを確認する。
