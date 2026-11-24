# SSH：A7C II に載っている sshd を使う

## 1. 公式にはどう使われているか

A7C II の sshd は「親子（マルチカメラ）接続」機能のサーバ側。
根拠：

- `lib/appFw.so` の機器記述に `<X_SSH_Support>` と `<X_SSH_QRSetupSupport>`。
- 同じ `appFw.so` のログ文に
  `sequence_parentchild_start_ssh_connection`、`start_ssh_client_session_list`、
  `m_parent` / `m_child_index` / `m_ssh_enable`、`SERVER_INFO_TYPE_SSH_INFO`。
- バックアップ側に子機19スロット分の定義（姉妹リポジトリの BKID 一覧より）：

  | プロパティ | 既定値 |
  | --- | --- |
  | `0x02cf184a`〜`0x02cf185c` `BKID_APP_PARENT_CHILD_SERVER_CAMERA_SSH_MODE0`〜`18` | `00` |
  | `0x02cf185d`〜`0x02cf186f` `…_SSH_INFO0`〜`18` | `00` |
  | `0x02cf18a9`〜`0x02cf18bb` `…_SSH_USERNAME0`〜`18` | 17バイトのゼロ |
  | `…_SSH_FINGER_PRINT_FIRST_HALF0`〜`18` ほか | — |

つまり**アカウント名・フィンガープリント・有効フラグはすべて BK4 バックアップに
永続化される**。バックアップは実機で読み書きできる（`bk r` / `bk w`）ので、
ここが「書き換え無しで触れる」唯一の面になる。

## 2. 起動と鍵のライフサイクル

`lib/libInfraSSHManager.so` の文字列から：

| 文字列 | 意味 |
| --- | --- |
| `SSHD_START_CMD` / `/usr/sbin/sshd` | 起動コマンド |
| `SSHD_STOP_CMD` / `/bin/busybox killall sshd` | 停止 |
| `/var/run/sshd.pid`、`/var/run/sshd` | PID と権限分離ディレクトリ |
| `CREATE_HOST_KEY_SHELL` / `/usr/bin/create_host_key.sh` | ホスト鍵生成 |
| `/tmp_network/ssh/ssh_host_ecdsa_key`（`.pub`） | ホスト鍵の置き場 |
| `/usr/bin/get_finger_print.sh` | フィンガープリント |
| `/tmp_network/ssh/ssh_name_password` | ログインアカウント定義 |
| `/tmp_network/ssh/ssh_session_count`、`…/ssh_auth_failed_count` | セッション数・失敗数 |

C++ シンボルからは `startSshd` / `stopSshd` / `getSshdPid` / `createKey` /
`deleteKey` / `createKeyFromBackup` / `updateBackupKey` / `deleteBackupKey` /
`createSshdDirectory` / `isKeyValid` / `isSshdStarted` が読める。
**ホスト鍵はバックアップから復元される**（`createKeyFromBackup`）設計。

`bin/create_host_key.sh` の中身は次のとおりで、パスフレーズなしの鍵を作る：

```sh
/usr/bin/ssh-keygen -q -b 256 -t ecdsa -N '' -f /tmp_network/ssh/ssh_host_ecdsa_key
```

p15 に `sshd_config` は入っていない。`sbin/sshd` のコンパイル時既定は
`/etc/ssh/sshd_config` で、そのパスも p15 には無い。したがって
**実際の設定は起動時に引数か生成ファイルで与えられている**。
何が渡っているかは未判明で、`PermitRootLogin` や `Subsystem sftp` の有無、
`AllowUsers` の内容が分からない限り「公式経路で sshd を立てればログインできる」
とは言えない。ここは実機ログか `appFw.so` の `SSHD_START_CMD` 構築箇所の
解析で埋める。

## 3. ログインアカウント：`libnss_ssh.so.2`

このモジュールが `/tmp_network/ssh/ssh_name_password` を読み、
`getpwnam` / `getpwuid` にアカウントを合成する。
ファイル形式は `/etc/passwd` 形式ではなく `name,x` のカンマ区切り1行。
素の状態での既定値は文字列テーブルから読み取れる：

| 項目 | 素の値 |
| --- | --- |
| home | `/bin` |
| shell | `/bin/false` |

**シェルが `/bin/false` なので、公式状態のままログインできても端末は取れない。**

A7C II 2.01 の `lib/libnss_ssh.so.2` は 10,192 バイト、SHA-256
`21c29cad2acc9af2183f81512a2ebdbc729bbf643fc41fd0cd28635944f051e4` で、
A7 IV 6.02 の同名ファイルと**完全に同一**。したがって A7 IV 向けに公開されている
改変表（この構成要素ではファイルオフセット＝VA）がそのまま使える：

| オフセット | 書き込む AArch64 u32 | 作用 |
| --- | --- | --- |
| `0x11b8`, `0x11cc`, `0x1348` | `0x52800000` | UID / GID を 0 で返す |
| `0x1264` | `0x7100001f` | UID 検索の分岐を 0 に合わせる |
| `0x11fc`, `0x1384` | `0xd28000a1` | home 文字列長の上限 5 |
| `0x122c`, `0x13b4` | `0xd28000e1` | shell 文字列長の上限 7 |

文字列スロット（スロット全体をゼロ埋めしてから NUL 終端で書く）：

| オフセット | 長さ | 新しい値 |
| --- | --- | --- |
| `0x1428` | 8 | `/root` |
| `0x1438` | 11 | `/bin/sh` |
| `0x1445` | 35 | `/usr/ssh/ssh_name_password` |

素の `/bin`（4+NUL）と `/bin/false`（10+NUL）がちょうどこの容量に収まることも、
A7C II 側の実測で確認した。

**注意**：上記は A7 IV 向けの値をそのまま転記したもので、A7C II の実機で
適用・検証はしていない。適用前に自分の機体から取り出した同一ファイルの
SHA-256 が上記と一致することを必ず確認する。

## 4. 起動フック：`bin/bootin.elf`

A7 IV 手法は `bootin.elf` の `main` を乗っ取り、二重 fork した子プロセスで
sshd を起動する。A7C II のファイルはハッシュが違うが寸法が一致する：

| 項目 | A7 IV 6.02（公開値） | A7C II 2.01（実測） |
| --- | --- | --- |
| ファイル長 | 23,960 | 23,960 |
| `main` VA | `0x4017e0` | 同オフセットに `fd7bbca9` = `stp x29,x30,[sp,#-0x40]!` |
| コードケーブ VA / オフセット | `0x404340` / `0x4340` | `0x4340` 以降ゼロ埋め |
| RX LOAD の延長先 | `0x4d58` | 元の RX LOAD は `0x42ec` まで、次の LOAD は `0x4d58` から |

`bootin.elf` は `ulogio` も参照しており、起動時の初期化を担っている。
A7C II 向けには、この寸法を前提にフックを再導出すればよい見込み。

## 5. 起動コマンドと鍵の在処（確定、2026-11-24）

`lib/libInfraSSHManager.so` を逆アセンブルして、前回「未判明」としていた
2点が確定した。

### 5a. sshd は引数なしで起動される

`SshFunctionWrapperImpl::startSshd()`（VA `0x908c`）は
`executeIMSystem()` に文字列 `/usr/sbin/sshd`（`.rodata` の `0xb172`）を
そのまま渡すだけ。**`-f` も `-E` も付かない。**

```asm
90bc:  adrp x1, 0xb000
90c4:  add  x1, x1, #0x172      ; "/usr/sbin/sshd"
90cc:  bl   executeIMSystem(const char*, int&)
```

停止側は `/bin/busybox killall sshd`（`0xb0ef`）。

したがって sshd は**コンパイル時の既定**で動く。バイナリの文字列から：

| 既定 | 値 |
| --- | --- |
| 設定ファイル | `/etc/ssh/sshd_config` |
| ホスト鍵 | `/etc/ssh/ssh_host_{ecdsa,ed25519,rsa}_key` |
| その他 | `/etc/ssh/moduli`、`/etc/nologin`、`/etc/motd`、`/bin/sh /etc/ssh/sshrc` |

**ここが効いてくる点：`/etc` は p15（読み取り専用）ではない。**
p3 initrd の `sbin/initrc/fstab.ext` は

```text
/dev/nflasha10	/etc	vfat	rw,nodiratime,noatime,sync,posix_attr	0	0
/dev/nflasha10	/var	vfat	rw,nodiratime,noatime,sync,posix_attr	0	0
```

で、`/etc` は**書き込み可能な不揮発パーティション**。
`sshd_config` も `nsswitch.conf` も `passwd` もそこにあるので、
**p15 を書き換えずに sshd の設定を変えられる可能性が高い**。
`PermitRootLogin` や `Subsystem sftp internal-sftp` を足すのに
ファームウェア改変が要らないかもしれない、ということ。

ただし **nflasha10 の中身はアップデートパッケージに入っていない**ので、
実際に何が置かれているか（`/etc/ssh/sshd_config` が存在するのか、
`/etc/passwd` に何が入っているのか、`nsswitch.conf` の `passwd:` 行が
`files ssh` なのか）は**実機を読まないと分からない**。
読み取り専用で確かめる項目として [TODO.md](../TODO.md) に入れた。

アカウントロックは PAM で、`/sbin/pam_tally2 --reset -u `（`0xb058`）を
`PAM_FAILURE_COUNT_RESET_CMD` として持っている。
失敗回数は `/tmp_network/ssh/ssh_auth_failed_count`、
セッション数は `/tmp_network/ssh/ssh_session_count`。

### 5b. ホスト秘密鍵はバックアップに入っている

`SshFunctionWrapperImpl::createKeyFromBackup()`（VA `0x885c`）：

```asm
88b0:  mov  w0, #0x3000000      ; BK ID
88ac:  mov  w2, #0x258          ; 600 bytes
88b4:  bl   Backup_nread
...                             ; 読めたら
8920:  ... "/tmp_network/ssh/ssh_host_ecdsa_key" を fopen して書き出し
8998:  mov  w1, #0x180          ; chmod 0600
```

`updateBackupKey()`（VA `0x97e8`）はその逆向きで、鍵データが 600 バイト以下で
あることを確かめてから `Backup_write(0x300, 0x03000000, buf)` を呼び、
`Backup_sync_subsystem(0x300)` で確定する。

| 項目 | 値 |
| --- | --- |
| バックアッププロパティ | **`0x03000000`** |
| サブシステム | `0x0300` |
| 長さ | 600 バイト（バッファは 601、NUL 終端込み） |
| 中身 | ECDSA-256 のホスト**秘密**鍵（`create_host_key.sh` が作る、パスフレーズなし） |

実機では `bk r 03000000` で読める見込み。**読んだ内容は公開しないこと**
（その機体のホスト鍵そのもの）。逆に `bk w` で自分の鍵を入れることもできる
はずで、これはファームウェアを触らずにホスト鍵を差し替えられるという意味になる。

## 6. まだ分かっていないこと


1. `/etc/ssh/sshd_config` が実機に存在するか、存在するなら中身は何か。
   `PermitRootLogin` と `Subsystem sftp` の有無で、必要な改変量が変わる。
2. `/etc/nsswitch.conf` の `passwd:` 行に `ssh` が入っているか。
   `files` も効くなら、`/etc/passwd` にアカウントを足すだけで済む可能性がある。
3. 親子接続が ILCE-7CM2（`PRODUCT_MODEL_PP`）で有効か。feature manager 側に
   SSH / 親子接続の可否フラグは見つかっていない。
4. `BKID_APP_PARENT_CHILD_SERVER_CAMERA_SSH_*` を `bk w` で立てたときに、
   メニューに出ないまま sshd が起きるのか、メニュー側の判定が先に効くのか。

1 と 2 は実機の**読み取り**で埋まる（nflasha10 はパッケージに入っていない）。
3 と 4 は実機のプロパティ実験（1件ずつ、復旧確認付き）。
