# 実機から取れた事実（ILCE-7CM2、2026-11-24）

`scripts/survey_readonly.py` の1回の読み取りで判明したもの。
**カメラには何も書き込んでいない。**

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

## `shell` は繋がらなかった（2026-11-24）

レベル A なので端末ゲート自体は開いており、PMCA の `shell` は
`Terminal activated.` まで進む。だが**入力したコマンドは一切届かず**、
`Ctrl+C` のあと空メッセージの `Error:` が出る。`id` 1文字でも同じ。

原因の第一候補は**エンドポイントの取り違え**。PMCA の
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

切り分けは `scripts/terminal_probe.py`：エンドポイントを列挙し、
端末を有効にしてから (OUT, IN) の全組み合わせに改行1つを送って応答を見る。
**全組で「write failed」なら前者、全組で「silent」なら後者。**

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
