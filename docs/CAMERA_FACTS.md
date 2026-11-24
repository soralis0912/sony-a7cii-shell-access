# 実機から取れた事実（ILCE-7CM2、2026-11-24）

> **ネイティブコード実行が成立した。** Jiritsu `SET_FILE` で自前の
> `libJit.so` を送ると、サービスプロセス（pid 532）が `dlopen` し、
> コンストラクタが **uid 0 / euid 0** で走った。
> 詳細： [JIRITSU_SET_FILE.md](JIRITSU_SET_FILE.md)。

`scripts/survey_readonly.py` の1回の読み取りで判明したもの。
**カメラには何も書き込んでいない。**

## 実行環境（jit_probe、2026-11-24）

読み取り専用ライブラリの報告から確定した事実。

### 我々のコードが走る場所

| 項目 | 値 |
| --- | --- |
| プロセス | **`/usr/bin/im.elf debug s g r u l i a lazy-global`**（pid 532、親 pid 1） |
| 権限 | `Uid: 0 0 0 0` / `Gid: 0 0 0 0` ＝ **完全な root** |
| ケーパビリティ | `CapEff: 0000003fffffffff` ＝ **全ケーパビリティ** |
| スレッド数 | 215 |
| RSS | 3.8 GB（カメラ本体アプリそのもの） |
| カーネル | `Linux 4.9.337-scel+ #1 SMP PREEMPT Sat Oct 11 04:09:59 JST 2025 aarch64` |

**サービスプロトコルの処理も、撮影アプリも、この同じプロセス。**
つまり我々のライブラリは `libsencore.so` と同じアドレス空間にいる。

### マウント（`/proc/mounts` 実測）

| マウント先 | 実体 | 種別 | 読み書き |
| --- | --- | --- | --- |
| `/` | `/dev/nflasha7` | ext2 | **ro** |
| `/usr` | `/dev/nflasha15` | ext2 | **ro** |
| `/tmp` | `/dev/nflasha10` | vfat | **rw** |
| **`/etc`** | **`/dev/nflasha10`** | **vfat** | **rw** |
| `/var` | `/dev/nflasha10` | vfat | rw |
| `/setting` | `/dev/nflasha2` | vfat | rw |
| `/system` | `/dev/nflasha3` | vfat | rw |
| `/cp` | `/dev/nflasha8` | vfat | rw |
| `/log` | `/dev/nflasha11` | vfat | rw |
| `/cert` | `/dev/nflasha12` | vfat | rw |
| `/lens` | `/dev/nflasha18` | vfat | rw |
| `/tmp/jiritsu` | `/dev/nflasha6` | vfat | rw |
| `/usr/data/lut` | `/dev/nflasha30` | vfat | **rw** |
| `/usr/data/ai_dict/usr` | `/dev/nflasha22` | vfat | rw |
| **`/tmp_wbshd`** | none | **tmpfs** | rw |
| **`/tmp_network`** | none | **tmpfs**（size=1024k） | rw |
| `/tmp_ipsec` / `/tmp_cloud` / `/tmp_bt` | none | tmpfs | rw |

- **`/etc` が書き込み可能であることが実機で確認できた。**
- **`/tmp_network` は tmpfs。** sshd のホスト鍵と `ssh_name_password` の
  置き場がここなので、[ON_MEMORY.md](ON_MEMORY.md) のオンメモリ SSH 設計は成立する。
- `/usr/data/lut` という**書き込み可能な LUT パーティション**がある（nflasha30）。

### シェルは実在する（前の未確認項目）

`/bin/sh`、`/bin/ash`、`/bin/busybox` がいずれも **423,000 バイト**で、
`sh` と `ash` は busybox へのシンボリックリンク。
**`/etc/passwd` のシェルを `/bin/sh` にすれば実在する。**
[SSH.md](SSH.md) 3章の NSS バイトパッチが不要という結論と合わせて、
**root SSH に必要なのは `/etc` の2ファイルの編集だけ**という見通しが固まった。

### SSH の材料は既に用意されている（2026-11-24、シェル経由で確認）

`/tmp_network/ssh`（tmpfs）の中身：

```text
drw-r-xr-x  2 root 0  120 Jan  1 00:53 .
-rw-r--r--  1 root 0    1 ssh_auth_failed_count
-rw-------  1 root 0  505 ssh_host_ecdsa_key      ← ホスト秘密鍵、mode 0600
-rw-r--r--  1 root 0   82 ssh_name_password       ← アカウント定義
-rw-r--r--  1 root 0    1 ssh_session_count
```

**ホスト鍵が生成済み**で、サイズ 505 バイトは
バックアッププロパティ `0x03000000`（600 バイト枠、非ゼロ 505 バイト）と一致する。
つまり `createKeyFromBackup` が起動時に走り、鍵が配置されている。
`ssh_name_password`（82 バイト）も存在する——`libnss_ssh.so.2` が読む
アカウント定義ファイル。

**形式の訂正：`name,x` ではない。** A7 IV 側の記録では第2欄は
使えないプレースホルダ `x` とされていたが、この機体の実物は

```text
<ユーザー名>,$5$rounds=5000$<salt>$<hash>
```

で、**第2欄は実在する SHA-256-crypt のパスワードハッシュ**。
`sshd_config` が `UsePAM yes` ＋ `ChallengeResponseAuthentication yes` なので、
親子接続はこのハッシュに対する認証でログインする設計と読める。

> **この中身は資格情報なので、本リポジトリには記録しない。**
> 実機で読むときも、出力をそのまま貼らないこと。

**sshd は走っていないが、材料は揃っている。**

### busybox の applet 一覧（実測）

**入っていないもの**：`tr` `head` `df` `id` `vi` `awk` `nc` `wget` `curl` `find` `ssh`

**入っていて効くもの**（抜粋）：

| 分類 | applet |
| --- | --- |
| 編集・加工 | `sed` `cut` `paste` `sort` `uniq` `nl` `wc` `xargs` `tail` `xxd` **`hexedit`** |
| ファイル | `cat` `cp` `mv` `rm` `ln` `chmod` `chown` `chgrp` `mkdir` `touch` `dd` `tar` `cpio` `md5sum` `sha1sum` `shred` `readlink` `mktemp` |
| プロセス | `ps` `kill` `killall` `pidof` `taskset` `setpriv` `nproc` `chroot` |
| ネットワーク | `ifconfig` `route` `ping` `ping6` **`telnet`** **`telnetd`** `ftpget` `ftpput` `ssl_client` `vconfig` `tc` |
| システム | `mount` `umount` `insmod` `rmmod` `lsmod` `modprobe` `mdev` `syslogd` `klogd` `dmesg` `stty` `getty` `login` `nologin` `init` `reboot` `poweroff` `halt` `switch_root` `pivot_root` `sfdisk` `partprobe` `freeramdisk` `swapon` `swapoff` |

**`telnetd` が入っている。** busybox の `telnetd -l /bin/sh` は
アカウントを介さずに指定したプログラムを直接起動するので、
**`/etc` を一切変更せずに TCP 経由の対話シェルが立つ**。
ulogio の telnet を追う必要はなかった。到達には IP 経路（Wi-Fi）が必要。

### ネットワークは USB モード中は死んでいる（2026-11-24 実測）

`/sys/class/net` にあるのは **`lo` / `gre0` / `gretap0` / `tunl0` の4つだけ**。
`wlan0` は**存在しない**（Wi-Fi ドライバが読み込まれていない）。
アドレスが付いているのは `lo`（127.0.0.1）のみで、
ルーティング表は空、`/proc/net/tcp` も空＝**listening ソケットは1つもない**。

つまり `telnetd` を立てても、USB モードのままでは Mac から到達できない。
到達経路を作るには、カメラ側で Wi-Fi を有効にする必要がある。
`telnetd` は `0.0.0.0` に bind できるので、**先に立てておいて
あとからインターフェースが上がってもよい**。

`/dev/pts` は devpts でマウント済み（`ptmxmode=000` だが root は開ける）なので、
`telnetd` が pty を取るのは問題ない見込み。

### `/etc` と `/var` は同じファイルシステム

`/var` の中身が `passwd`（124 バイト）・`nsswitch.conf`（280 バイト）・
`ssh/`・`pam.d/`・`protocols`・`services` で、`/etc` と一致する。
`/proc/mounts` でも nflasha10 が `/etc` と `/var` の両方にマウントされている。
つまり `/var/passwd` と `/etc/passwd` は同一ファイル。

その他：`/var/mtab` は `../proc/mounts` へのリンク、
`/var/kikilog.dat` は 4.2 MB、`/var/jiritsu` は `dr-x------`。
`/root` は uid 57285 / gid 1000 所有で `chassis` と `common.src` の2ファイルだけ。

### SSH の現状

| 項目 | 実測 |
| --- | --- |
| `/etc/ssh` の中身 | **`sshd_config` だけ。ホスト鍵は置かれていない**（`/tmp_network` 側に生成される） |
| `/etc/shadow` | **存在しない** |
| `/etc/passwd` | 124 バイト（root は `*`、シェル `/bin/false`） |
| `sshd` プロセス | **走っていない** |

`shadow` が無いので、パスワード認証を使うなら `/etc/passwd` の第2欄に
ハッシュを入れる形になる。鍵認証のほうが素直。

### 走っているプロセスは5つだけ

```text
1     /bin/busybox sh /sbin/init2
518   /usr/bin/bootin.elf
528   /bin/ash --                     ← setup_console が回しているコンソールシェル
532   /usr/bin/im.elf ...             ← 我々のコードが走っている場所
1520  /usr/bin/bsa_server ...         （Bluetooth）
```

**pid 528 の `/bin/ash --` が待機している。** これが
[TERMINAL_GATE.md](TERMINAL_GATE.md) で追っていた「コンソールのシェル」で、
端末を開けば繋がる相手。

`/tmp/jbusy` と `/tmp/jmode` はいずれも存在しない。

## サービス権限レベルは A

| 問い | 結果 |
| --- | --- |
| `0x40` AdjustControl | ok |
| `0x10` ProductInfo | ok |
| 端末ゲート（`0x00f1`、値 0） | **ok ＝ ゲートは開いている** |
| 判定 | **レベル A（`adjCodeLevel == 3`）** |

`libsencore.so` の `onComplete` が `terminal_change_function_is_disabled =
(level != 3)` を設定する（IDA で確認済み）ので、レベル A ＝ 端末切り替えが
通る状態。**`serviceshell` の `shell` が使える見込み**で、通常起動の initrd が
`ash --login` を回しているコンソールに、書き込みゼロで繋がる。

Senser FileControl（`0xff01`）は `error 128` で拒否された。
どのレベルのテーブルにも無いという静的判定の裏が取れた。

## USB 端末は**存在しない**（2026-11-24、静的解析で確定）

`shell` が通らない理由は、エンドポイントでも ulogio でもホスト側でもなかった。
**端末有効化コマンド自体が何もしないスタブ**だった。

`ProductInfoFunc` は受け取ったコマンドをプラグインモジュールへ振る：

```c
PluginModule = GetPluginModule("libpro%02X.so", 0x10u, HIBYTE(v6));
return CreatePluginCommand(PluginModule, v6, ...);
```

コマンド `0x00F1`（TERM_CHANGE）は上位バイト `0x00` なので
**`lib/libpro00.so`** の `command00F1` に入る。そのモジュールは 6,032 バイトで、
エクスポートは `command001F`（READ_HASP）と `command00F1` の2つだけ。
`command00F1` の中身は**8バイト**：

```asm
0000000000000a64 <command00F1>:
     a64:  mov  w0, #0x1      ; 成功を返す
     a68:  ret
```

比較のため `command001F` は 0xc0 バイトあり、`Read_Hasp` / `Reset_Hasp` を
実際に呼んでログも出す。つまり **`0x00F1` だけが中身を抜かれている**。

これで観測が全部つながる：

| 観測 | 説明 |
| --- | --- |
| ゲートは開いている（レベル A） | `terminal_change_function_is_disabled == 0`。ここは本物 |
| `Terminal activated.` と出る | コマンドが成功（`1`）を返すから。PMCA はそれを信じる |
| 入力が一切届かない | 端末は作られていない。OUT `0x04` を読む主体がいない |
| 空の `Error:` | 書き込みが USB エラーになり、PMCA がメッセージを捨てる |

**A7 IV で「ULOGIO の復元」が必要だったのと同じ構図。** あちらは 6.02 で
端末生成コードが削られていたので旧 1.05 から移植していた。A7C II 2.01 では
ulogio 側のコード（telnetd 含む）は残っているが、**サービス側の入口が
スタブ化**されている。

### telnetd にも呼び出し元がいない

`libosal_ulogio.so` の `ulogio_telnetd_init`（VA `0x50b4`）への参照は
PLT/GOT（`0xc80` / `0x19310`）だけで、**ライブラリ内にも他のバイナリにも
呼び出し元が無い**（p15 全体を検索しても import しているのは
`libosal_ulogio.so` 自身のみ）。`ulogio_filter_userspace_init` も同じ形。

つまり **`TELN = 1` にしただけで telnet が上がる保証は無い**。
フラグを読むのはカーネルモジュール側なので、listener を実際に起こすのが
誰なのかは kmod 側の確認が必要（未了）。

### 残っている現実的な経路

| 経路 | 状態 |
| --- | --- |
| USB 端末 | **死んでいる**。入口がスタブ。コード改変なしでは無理 |
| telnet | フラグは書けるが、起こす主体が未確認 |
| **SSH** | **最有力**。sshd は appFw の InfraSshManager が実際に起動する経路を持ち、設定は書き込み可能な `/etc` にある |

どれも結局 **書き込み手段**（Jiritsu `SET_FILE` `0x4007`）に戻る。
読み取りは実機で通っているので、次に検証すべきはそこ。

## 旧記述：`shell` は繋がらなかった（2026-11-24）

レベル A なので端末ゲート自体は開いており、PMCA の `shell` は
`Terminal activated.` まで進む。だが**入力したコマンドは一切届かず**、
`Ctrl+C` のあと空メッセージの `Error:` が出る。`id` 1文字でも同じ。

### エンドポイントは正しかった（2026-11-24、実機で確認）

```text
0x81 bulk IN / 0x02 bulk OUT / 0x83 bulk IN / 0x04 bulk OUT（各 512 バイト）
bulk IN  [0]=0x81, [1]=0x83      bulk OUT [0]=0x02, [1]=0x04
```

PMCA の添字1は **IN `0x83` / OUT `0x04`** に解決され、これは A7 IV の
公開値と**完全に一致**する。つまり第一候補（エンドポイントの取り違え）は**消えた**。

### 空の `Error:` の正体

PMCA の libusb バックエンドは、あらゆる `usb.core.USBError` を
**引数なしの** `GenericUsbException()` に置き換える：

```python
def write(self, ep, data):
  try: self.dev.write(ep, data)
  except usb.core.USBError: raise GenericUsbException()
```

`print('Error: %s' % e)` が空になるのはこのため。
`readTerminal` はこの例外を飲んで `b""` を返すが、`writeTerminal` は飲まない。
**つまりセッションを終わらせているのは OUT `0x04` への書き込み**で、
本当のエラー（stall なのかホスト側の拒否なのか）は捨てられている。

それを拾うのが `scripts/terminal_write_error.py`。`shell` と同じことを
同じエンドポイントで1回だけやって、`errno` / `strerror` まで出す。

### 原因の第一候補だったもの（記録として残す）

**エンドポイントの取り違え**。PMCA の
`SenserPlatformBackend.interactiveShell` は `driver.read/write(..., ep=1)` を
使うが、`GenericUsbDriver` の `ep` は**エンドポイントアドレスではなく、
見つけたバルクエンドポイント列の添字**：

```python
def read(self, length, ep=0, timeout=None):
  return self.backend.read(self.epIn[ep], length, timeout)
def write(self, data, ep=0):
  self.backend.write(self.epOut[ep], data)
```

A7 IV の公開資料では USB 端末は IN `0x83` / OUT `0x04`。A7C II の
サービスインタフェースのエンドポイント構成が違えば、添字 1 は別の
エンドポイントを指すか、そもそも存在しない。`readTerminal` は例外を
飲んで空を返す実装なので、**失敗しているのは書き込み側**と考えられる。

第二候補は、**端末は存在するが対話シェルが結び付いていない**こと。
`libosal_ulogio.so` の `.data` には
`Default interactive subsys is not set and latest switched subsys does not ...`
という文字列があり、この機体の `/setting/ulogio.bin` は **`ISYS = 0`**
（下記）。端末に流れるのはログだけで、入力を受ける主体がいない可能性がある。

切り分けは `scripts/terminal_probe.py`。**ディスクリプタを読むだけ**で、
どのエンドポイントにも何も送らない。添字1が何に解決されるか、
そもそもバルクエンドポイントが2本あるのかが分かれば、第一候補は判定できる。

> 当初この切り分けを「(OUT, IN) の全組に改行を送って応答を見る」方式で
> 書いたが、実行したら **ホスト（Mac）が固まった**。カーネルが握っている
> バルクエンドポイントへ当てずっぽうに書いてはいけない。
> カメラ側に不揮発の影響は無い（端末フラグは RAM のみ）。

## `/etc/ssh/sshd_config` は存在し、**書き込み可能な** nflasha10 にある

3,094 バイト。要点だけ：

| 設定 | 値 | 意味 |
| --- | --- | --- |
| `Port 22` / `Protocol 2` | — | 待ち受けは 22 |
| `HostKey` | `/tmp_network/ssh/ssh_host_ecdsa_key` | バックアップ `0x03000000` から復元される鍵 |
| **`PermitRootLogin`** | **`no`** | root ログイン不可 |
| **`PubkeyAuthentication`** | **`no`** | 公開鍵認証**無効** |
| `PasswordAuthentication` | `no` | パスワード不可 |
| `ChallengeResponseAuthentication` | `yes` | ＋ `UsePAM yes`。公式の認証経路はこれ |
| `KbdInteractiveAuthentication` | `no` | — |
| **`MaxSessions`** | **`0`** | **セッションを一切張らせない** |
| `Subsystem sftp` | コメントアウト | **SFTP 無効** |
| `PermitOpen` | `localhost:15740 localhost:60152` | 15740 は PTP/IP。**用途はトンネル** |
| `AllowTcpForwarding` | `yes` | 同上 |
| `ForceCommand` / `ChrootDirectory` | `none` | — |
| `UsePrivilegeSeparation` / `StrictModes` | `yes` | — |
| `HostKeyAlgorithms` / `Kex` / `MACs` / `Ciphers` | ecdsa-sha2-nistp256 / ecdh-sha2-nistp256 / hmac-sha2-256 / aes128-ctr | 1種ずつに限定 |

つまり公式の sshd は**子機が親機の PTP/IP ポートへ張るトンネル専用**で、
対話シェルは `MaxSessions 0` と `PermitRootLogin no` で二重に閉じてある。

## `/etc/nsswitch.conf` が `files` を見ている

```text
passwd:		files ssh
group:		files
shadow:		files
```

**`files` が先に来る。** つまり `/etc/passwd` のエントリがそのまま効くので、
[SSH.md](SSH.md) に書いた `libnss_ssh.so.2` のバイトパッチは**不要**。

## `/etc/passwd`（124 バイト、ハッシュは入っていない）

```text
root:*:0:0:root:/root:/bin/false
sshd:*:77:77:sshd:/var/run/sshd:/bin/false
nobody:*:99:65534:nobody:/noexistent:/bin/false
```

- root は uid 0 で存在するが **シェルが `/bin/false`**、パスワード欄は `*`（無効）。
- 影のハッシュは `shadow: files` 側。`/etc/shadow` は未取得。

## `/setting/ulogio.bin`（2,900 バイト、109 レコード）

`scripts/ulogio_filter_file.py --parse` が完走した。現状の値：

| タグ | 値 |
| --- | --- |
| **`TELN`** | **0 ＝ telnet は無効** |
| `TERM` | 1（端末出力は有効） |
| `DBGL` | 1 |
| `FLTA` / `PROX` | 0 |
| `FLTF` | `/setting/filter.bin`（フィルタ設定は**別ファイル**） |
| `RCVF` | `/log/escapelog.bin` |
| `ALGP` / `ALGB` / `ALGD` / `ALGK` | `/log/` と各ログファイル名 |
| `LGNM` | ビルド名の文字列 |
| `SUBS` × 多数 | サブシステムごとのフィルタ |

**12バイトの最小ファイルを作って置き換えてはいけない。**
109 レコードが消える。`--edit` で現物の `TELN` だけを書き換える：

```bash
python3 scripts/ulogio_filter_file.py --edit <取得した ulogio.bin> --telnet 1 \
  -o ulogio_telnet_on.bin
```

実機の現物に対して試した結果、**2,900 バイトのうち 1 バイト（`0xac`）だけ**が
変わることを確認済み。

## ここから何が言えるか

1. **root SSH にファームウェア改変は要らない見込み。**
   必要なのは nflasha10 上の2ファイルの編集：
   - `/etc/ssh/sshd_config`：`PermitRootLogin yes`、`PubkeyAuthentication yes`、
     `AuthorizedKeysFile`、`MaxSessions`（0 以外）、必要なら
     `Subsystem sftp internal-sftp`
   - `/etc/passwd`：root のシェルを実在するものにする（`/bin/false` のままでは
     ログインできても何も起きない）。**どのシェルが実在するかは未確認**
     （p15 の p7 側には `/bin/busybox` があるが `/bin/sh` は見えていない）
2. **telnet は `/setting/ulogio.bin` の 1 バイトで足りる。** ただし不揮発。
3. どちらも**書き込み手段が必要**。レベル A なら `shell` が最も安全
   （書き込みゼロでまず中を見られる）。Jiritsu の `SET_FILE` はまだ未検証。
