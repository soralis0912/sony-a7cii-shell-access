# 可否判定：A7C II で root シェルは成立するか

対象：ILCE-7CM2 Ver. 2.01、p15（`/dev/nflasha15`）の展開結果。
判定は **静的解析のみ**。実機で実行した操作は、姉妹リポジトリで済んでいる
サービスモード認証・バックアップ取得・`bk r` 読み取りまで。

## 1. 部品の在庫（確認済み）

展開した p15 に、root 端末を成立させる部品が揃っている。

| 部品 | サイズ | 役割 |
| --- | ---: | --- |
| `sbin/sshd` | 767,408 | Sony が同梱している OpenSSH デーモン |
| `bin/ssh-keygen` | 416,976 | ホスト鍵生成 |
| `bin/create_host_key.sh` | 302 | パスフレーズなし ECDSA-256 ホスト鍵を作る公式スクリプト |
| `bin/get_finger_print.sh` | 168 | ホスト鍵フィンガープリント表示 |
| `bin/ssh_session_monitoring` | 101,296 | セッション監視 |
| `bin/ssh_account_lock_recorder` | 101,552 | ログイン失敗ロック記録 |
| `lib/libnss_ssh.so.2` | 10,192 | ログインアカウントを合成する NSS モジュール |
| `lib/libInfraSSHManager.so` | 60,360 | sshd の起動・停止、ホスト鍵のバックアップ保存 |
| `lib/libssh2.so.1.0.1` | 216,784 | SSH クライアント側（親子接続の子機→親機） |
| `lib/libosal_ulogio.so` | 40,168 | ulogio：**telnetd 実装を含む**ログ基盤 |
| `bin/ulogio` / `bin/ulogio.elf` | 101,880 / 28,656 | ulogio の CLI（`telnet up`、`term on` ほか） |
| `bin/bootin.elf` | 23,960 | 起動時ランチャ。A7 IV 手法でのフック先 |
| `lib/libsencore.so` | 385,520 | サービス（Senser/Jiritsu）コマンド処理と `dlopen` |
| `lib/libJiritsu.so` | 233,416 | Jiritsu コマンド実装 |

ハッシュは [evidence/component-inventory-a7cii-201.json](../evidence/component-inventory-a7cii-201.json)。

## 2. A7 IV の公開手法がどこまで流用できるか

A7 IV（ILCE-7M4）6.02 向けに公開されている SSH / Telnet 手法と、
A7C II 2.01 の同名部品を SHA-256 で突き合わせた結果：

| 部品 | A7C II 2.01 | 判定 |
| --- | --- | --- |
| `lib/libnss_ssh.so.2` | `21c29cad…f051e4` | **A7 IV 6.02 と完全一致。** 公開されているワードパッチ8箇所・文字列スロット3箇所がそのまま適用できる |
| `bin/bootin.elf` | `dab3ce4b…` （A7 IV は `82894d65…`） | 不一致だが**レイアウトは一致**。ファイル長 23,960、`main` 相当 VA `0x4017e0` の先頭が `fd7bbca9`（`stp x29,x30,[sp,#-0x40]!`）、RX LOAD は `0x42ec` までで `0x4340` 以降がゼロ埋め、次の LOAD が `0x4d58` から。A7 IV のフック設計（`0x404340` のコードケーブへ飛ばし RX を `0x4d58` まで延長）がそのまま成り立つ寸法 |
| `lib/libosal_ulogio.so` | `ce8ecde7…` | 不一致。ただし telnetd が**残存**しており、A7 IV 6.02 で必要だった旧 1.05 からの移植が不要。`ulogio_telnetd_init` は VA `0x50b4`（A7 IV 6.02 のパッチ対象 VA と同じ） |
| `lib/libsencore.so` | `3362d4b6…` | 不一致。ただし Jiritsu のコマンド集合と `dlopen` 経路は同等（下記3） |

結論：**SSH の肝である NSS 改変はバイト単位で流用可能**、起動フックは
寸法が一致するので再導出が軽い、Telnet は A7 IV より条件が良い。

## 3. 本当の関門：書き込みと実行

上記はすべて「p15 の中身をこう変えればよい」という話で、
A7C II では **p15 を書き換える手段がまだ確立していない**。
現在の手札と候補は [WRITE_PATHS.md](WRITE_PATHS.md) に分けた。要点だけ：

- **確立済み**：サービスモード認証、BK4 バックアップの読み（`bk r`）と
  書き戻し（`bk w` / `bk s`、未実験）。これは**プロパティ単位**で、
  ファイルシステムは触れない。
- **有望・未検証**：`libsencore.so` が `@JIRITSU_SET_FILE` / `SET_FILE2` /
  `SET_FILE_PATH` / `FILE_DELETE` / `MOUNT` / `FIRMUP` を持ち、
  `libpro%02X.so` / `libtestcmd.so` を `dlopen` する。A7 IV の
  「認証済みサービスプロセスに一時 `.so` を読み込ませて EUID 0 で実行」
  と同種の原語が存在する可能性が高い。
- **A7 IV と事情が違う点**：A7C II 2.01 のパッケージには p1 パーティション
  イメージが無く、更新系は `updater.img` と p15 内 `bin/udtrbody.bin` に分かれる。
  署名検証を無効化する A7 IV の p1 オフセット表は**そのまま使えない**。
  p15 には `libfileinputupdaterapi.so`、`libcryptfileinputupdaterapi.so`、
  `libupdatercorecommon.so`、`libupdaterufp.so` があり、いずれもシンボルは
  除去済み。オフセットは再導出が必要。
- **Fastboot / BootROM**：A7 IV と同じ CXD90057 なので上流（ILCE-7M4-RE）の
  成果が効く見込みはあるが、A7C II の Multi 端子と起動ストラップは未確認。
  最初に試す経路としては勧めない。

## 4. 現時点の判定

| 問い | 判定 | 根拠の強さ |
| --- | --- | --- |
| 部品は揃っているか | はい | 展開済み 2.01 の実測（強い） |
| パッチ設計を流用できるか | 大部分はい | ハッシュ一致とレイアウト一致（強い） |
| カメラに載せる経路があるか | 未確立・有望 | コマンド名と `dlopen` の存在のみ（弱い） |
| 実機でシェルが取れたか | いいえ | 未実施 |

次の一手は、**ファームウェアを一切書き換えずに済む順**に並べてある
[TODO.md](../TODO.md) のとおり。危険度の低い読み取り確認から始める。
