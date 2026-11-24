# オンメモリだけで SSH / Telnet を有効にできるか

「恒久的な書き込みをせず、電源を切れば元に戻る状態で端末を取れるか」の調査。
対象は ILCE-7CM2 Ver. 2.01。**結論：条件つきで可能。鍵になるのはサービス
権限レベルで、A7C II では1バイトのフラグがそれを決めている。**

## 0. まず判定が必要な1点

| 問い | 判定方法 |
| --- | --- |
| 認証で**レベル A**（`adjCodeLevel == 3`）に到達しているか | `scripts/probe_service_level.py`（読み取りのみ） |

到達していれば、**何も書き込まずに USB 端末（＝カメラのコンソール）が開く**。
到達していなければ、サービスプロトコルだけではオンメモリ経路が無い。
理由は以下。

## 1. サービスプロトコルは3段階の権限テーブルで動いている

`lib/libsencore.so` の `.data` にディスパッチテーブルが3つあり、
`WorkerThreadManager::onComplete(int)`（VA `0xc1d8`）が認証結果に応じて
どれを使うか選ぶ。テーブルの中身は実測：

| レベル | `adjCodeLevel` | 受け付ける PFUNC |
| --- | --- | --- |
| A（`pFunc_level_A`、VA `0x6d848`） | 3 | `0x10` ProductInfo、`0x20` FirmwareUpdate、`0x30` MiconAccess、`0x40` AdjustControl、`0xff00` TestMode、`0xff02` Sonar |
| B（`pFunc_level_B`、VA `0x6d8b8`） | 2 | `0x40`、`0x10`、`0x20` |
| C（`pFunc_level_C`、VA `0x6d8f8`） | 1 | `0x40` のみ |
| （なし） | 0 | — |

同じ `onComplete` の末尾がこうなっている（`w1` が選ばれたレベル）：

```asm
c210:  cmp  w1, #0x3
c21c:  cset w2, ne
c224:  strb w2, [x1]      ; terminal_change_function_is_disabled = (level != 3)
```

つまり **`terminal_change_function_is_disabled` はレベル A のときだけ 0 になる**。

`_Z15ProductInfoFuncPK12SenserPacket`（VA `0xeb8c`）はこのバイトを見て、
立っていれば端末切り替えコマンド（`0x00f1` TERM_CHANGE）を捨てる：

```asm
ebd8:  adrp x0, 0x6c000
ebdc:  ldr  x0, [x0, #0xeb0]   ; GOT: terminal_change_function_is_disabled
ebe0:  ldrb w0, [x0]
ebe4:  cbz  w0, 0xec24         ; 0 なら処理を続ける
ebe8:  ...                     ; 非0 なら DiscardRecvData
```

このバイトは `libsencore.so` の**書き込み可能な `.data`**（VA `0x6d9a0`、
ファイルオフセット `0x5d9a0`）にあり、ファイル上の初期値は **`01`（無効）**。
起動直後は無効で、認証でレベル A を取ったときだけ 0 になる、という作り。

## 2. レベル A なら「書き込みゼロ」で端末が開く

- PMCA の `serviceshell` には `shell` コマンドがあり、`setTerminalEnable(True)`
  （`0x00f1` TERM_CHANGE ＋ AdjustControl `0x601/0x1f` SENSER_TERM_MODE）を送って
  USB バルクのエンドポイント1で端末を読み書きする。
  実装は `pmca/platform/backend/senser.py` の `interactiveShell`。
- カメラ側のコンソールには**最初からシェルが走っている**。通常起動の
  initrd（p3）の `sbin/init2` は最後に `setup_console` を読み、

  ```sh
  TTYCMD="ash --login"
  while true; do $TTYCMD; done
  ```

  を回している。`/proc/cmdline` に `console=` が無ければ UART ではなく
  そのままこのコンソールが使われる。
- したがってレベル A では、**端末を有効化 → ログイン不要の root シェル**で、
  バックアップにもファイルシステムにも1バイトも書かない。
  終了時に PMCA が `setTerminalEnable(False)` を送って元に戻す。

これが本件の「オンメモリだけ」の本命。

## 3. レベル B / C だと行き止まり

- 端末ゲートが閉じているので `0x00f1` は拒否される。
- `0xff00` TestMode（＝Jiritsu のフロントエンド）も**レベル A のテーブルにしかない**。
  つまり Jiritsu の `SET_FILE` / `GET_FILE2` も使えない。
- `0xff01` FileControl と `0xff03` MemoryDump は**どのレベルのテーブルにも無い**。
  PMCA の `push` / `pull` / `bootrom` は、この機種では通らない見込み
  （`0xff03` 用の転送コードは `SubsystemCommunicationCommand::TransactionStart`
  に残っていて、サブシステムコマンド `0x421` に変換している。到達可能かは実測が必要）。
- 残るのは `0x40` AdjustControl、すなわちバックアッププロパティ（`bk r/w/s`）。
  これは**不揮発への書き込み**で、オンメモリではない。

要するに、**ゲートを開けるにはメモリ書き込みが必要で、メモリ書き込みの手段が
ゲートの先にある**という構造になっている。レベル B/C からオンメモリで抜ける道は、
現時点では見つかっていない。

## 4. 「オンメモリ」の範囲で何が書けるか（端末が取れた後）

端末が開いたあとに恒久化を避けるには、どこが揮発かを知る必要がある。
p3 initrd の `sbin/initrc/fstab` と `fstab.ext` の実測：

| マウント先 | 実体 | 揮発性 |
| --- | --- | --- |
| `/tmp_wbshd` | `tmpfs`（`init2` が mount） | **揮発（RAM）** |
| `/tmp` | `/dev/nflasha10` vfat | **残る**（名前に反して不揮発） |
| `/etc`、`/var` | `/dev/nflasha10` vfat | **残る** |
| `/setting` | `/dev/nflasha2` vfat | 残る |
| `/log` | `/dev/nflasha11` vfat | 残る |
| `/system` | `/dev/nflasha3` vfat | 残る |
| `/cp` | `/dev/nflasha8` vfat | 残る |
| `/usr` | `/dev/nflasha15` ext2 | **読み取り専用マウント** |

重要な点が2つ。

1. **`/tmp` は tmpfs ではない。** オンメモリで作業するなら `/tmp_wbshd` を使う。
2. **`/usr`（p15）は ro マウント**なので、前の調査で書いた p15 改変は
   実行中には当てられない（＝フラッシュ書き換えが必要）。
   逆に、オンメモリ運用では p15 を触らない設計にする必要がある。

## 5. オンメモリ SSH の設計（端末が取れた前提、未検証）

`/usr/sbin/sshd` はあるが、公式状態では NSS のシェルが `/bin/false`
（[SSH.md](SSH.md)）。p15 は ro なので差し替えられない。回避は2通り。

### 5a. シェルを使わない：SFTP だけ

`sbin/sshd` の文字列に `internal-sftp`、`forcecommand`、`permitrootlogin` があり、
**プロセス内 SFTP** に対応している。`internal-sftp` はユーザーのシェルを
exec しないので `/bin/false` の影響を受けない。

```text
Port 22
HostKey /tmp_wbshd/ssh/ssh_host_ecdsa_key
AuthorizedKeysFile /tmp_wbshd/ssh/authorized_keys
PasswordAuthentication no
PermitRootLogin yes
UsePAM no
StrictModes no
Subsystem sftp internal-sftp
ForceCommand internal-sftp
```

設定・鍵・`ssh_name_password` をすべて `/tmp_wbshd` に置き、
`sshd -f /tmp_wbshd/ssh/sshd_config` で起動すれば**不揮発には何も残らない**。
ホスト鍵は `/usr/bin/create_host_key.sh` と同じ要領（`ssh-keygen -t ecdsa -b 256 -N ''`）で
その場で作る。

### 5b. 対話シェルが要るなら：NSS を RAM 上の複製に差し替える

`libnss_ssh.so.2` は glibc が `dlopen` で名前解決して読み込むので、
**プロセスの `LD_LIBRARY_PATH` で差し替えられる**（sshd は root 実行で
setuid ではないため探索パスが効く）。

1. ro の `/usr/lib/libnss_ssh.so.2` を `/tmp_wbshd/lib/` にコピーする。
2. コピーに [SSH.md](SSH.md) の改変（UID/GID 0、home `/root`、shell `/bin/sh`）を当てる。
   このファイルは A7 IV 6.02 と同一なので、オフセットはそのまま使える。
3. `LD_LIBRARY_PATH=/tmp_wbshd/lib:/usr/lib:/lib /usr/sbin/sshd -f …` で起動する。

p15 も `/etc/nsswitch.conf` も触らない。再起動で消える。
**`/bin/sh` が実在するかは要確認**（p7 の `/bin` には `busybox` はあるが
`sh` は見えていない。無ければ shell 文字列は `/bin/busybox` 系に合わせて
長さ制約（7バイト）内で決め直す必要がある）。

## 6. オンメモリ Telnet は向かない

`ulogio telnet up` はフラグを保存して**再起動が必要**（CLI のヘルプにそう書いてある）。
保存先はまだ特定できていない（[TELNET_ULOGIO.md](TELNET_ULOGIO.md)）ため、
「オンメモリだけ」の条件には合わない。
USB 端末が取れるなら、そもそも telnet を上げる必要がない。

プロセス内で `ulogio_telnetd_init` を直接呼べば RAM だけで listener を
起こせる可能性はあるが、それには任意コード実行が必要で、
端末が取れている状況ならすでに目的を達している。

## 7. 判定まとめ

| 手段 | 不揮発への書き込み | 可否 |
| --- | --- | --- |
| サービス USB 端末（レベル A） | **なし** | **レベル A なら可。最優先で確認する** |
| `/tmp_wbshd` 上で sshd（SFTP のみ） | なし | 端末が取れた後なら可（設計済み・未検証） |
| `/tmp_wbshd` 上で sshd（NSS 差し替えで対話シェル） | なし | 同上。`/bin/sh` の実在確認が必要 |
| Telnet（`ulogio telnet up`） | あり（フラグ保存＋再起動） | オンメモリ不可 |
| バックアッププロパティで親子接続 SSH | あり（BK4） | オンメモリ不可 |
| p15 改変（NSS / bootin フック） | あり（フラッシュ） | オンメモリ不可。`/usr` は ro |

次の一手は [TODO.md](../TODO.md) のセクション H。
