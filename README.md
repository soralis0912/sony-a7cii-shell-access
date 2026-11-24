# Sony A7C II シェルアクセス調査（SSH / Telnet / サービス端末）

自己責任で利用してください。本リポジトリの利用による損害について、作者は責任を負いません。
ファームウェアの書き換えはカメラを恒久的に起動不能にし、撮影データ・調整値・設定を
破壊しうる操作です。保証・修理・公式アップデートにも影響します。

Sony **ILCE-7CM2**（A7C II）Ver. **2.01** で root シェル（SSH / Telnet / サービス USB 端末）が
成立しうるかを、公式アップデートの展開結果とサービスモードの実測から判定するための
リポジトリです。**ここにあるのは静的解析による可否判定と検証計画で、実機での
シェル取得は未達成**です。

- **実機から取れた事実（2026-11-24）**： [docs/CAMERA_FACTS.md](docs/CAMERA_FACTS.md)
- **ネイティブコード実行の経路**： [docs/JIRITSU_SET_FILE.md](docs/JIRITSU_SET_FILE.md)
- **実機を触るときの手順書**： [docs/FIELD_SESSION.md](docs/FIELD_SESSION.md)
- 判定の要約： [docs/FEASIBILITY.md](docs/FEASIBILITY.md)
- **オンメモリ（不揮発に書かずに）取れるか**： [docs/ON_MEMORY.md](docs/ON_MEMORY.md)
- SSH（既存 sshd の再利用）： [docs/SSH.md](docs/SSH.md)
- Telnet / ulogio： [docs/TELNET_ULOGIO.md](docs/TELNET_ULOGIO.md)
- 書き込み・実行経路（ここが本当の関門）： [docs/WRITE_PATHS.md](docs/WRITE_PATHS.md)
- SSH 以外の機能： [docs/OTHER_FEATURES.md](docs/OTHER_FEATURES.md)
- 次にやること： [TODO.md](TODO.md)
- 参照元と帰属： [REFERENCES.md](REFERENCES.md)

## 到達点

> **ネットワーク越しの対話 root シェルに入れた（2026-11-25）。**
> `busybox telnetd -l /bin/sh` をコマンドチャネルから起動し、
> `nc <IP> 2323` で接続。`/etc`・`/setting`・バックアップ・ファームウェアは未変更で、
> 止めれば（または電源を切れば）何も残らない。
> 経緯： [docs/CAMERA_FACTS.md](docs/CAMERA_FACTS.md)。

### そこまでの道筋（2026-11-24）

**普通の USB ケーブル経由で、カメラ上で任意のシェルコマンドを root 実行し、
出力を読み戻せる。** 経路は Jiritsu の `SET_FILE`（カテゴリ `0x1001` /
コマンド `0x4007`）で、索引1にコマンド文、索引2に自前の共有ライブラリを書くと
`adj_cmd_set_file` がそれを `dlopen` し、コンストラクタが
`/bin/sh -c` でコマンドを実行して出力をファイルに落とす。
証拠と手順： [docs/JIRITSU_SET_FILE.md](docs/JIRITSU_SET_FILE.md)。

```bash
sudo ./venv/bin/python .../jit_load.py .../libJit_sh.so --run 'uname -a; ps'
```

ファームウェアの書き換えも署名回避も端末ゲートの解除も**不要だった**。
USB 端末（`shell`）は結局使っていない。

## 結論（2026-11-24 時点）

| 問い | 答え |
| --- | --- |
| A7C II に SSH サーバは載っているか | **載っている。** `/usr/sbin/sshd` 本体、`ssh-keygen`、ホスト鍵生成スクリプト、セッション監視、アカウントロック記録、NSS モジュール、`libssh2` がすべて 2.01 の p15 に入っている |
| それは何のための sshd か | 公式機能「親子（マルチカメラ）接続」のサーバ側。機器記述に `X_SSH_Support` / `X_SSH_QRSetupSupport`、バックアップに子機19スロット分の `BKID_APP_PARENT_CHILD_SERVER_CAMERA_SSH_*` がある |
| A7 IV の SSH 手法はそのまま効くか | **要の1ファイルは完全に同一。** `lib/libnss_ssh.so.2`（10,192 バイト）は A7 IV 6.02 と SHA-256 が一致するので、公開されている8箇所のワードパッチと3つの文字列スロットがバイト単位でそのまま当たる |
| Telnet はどうか | A7 IV 6.02 より条件が良い。`libosal_ulogio.so` に telnetd の実装（`ulogio_telnetd_init` / `_mainloop` / `ulogio_filter_set_telnet`）が**残っている**ので、旧版からの移植が不要。有効化フラグの在処も確定：`/setting/ulogio.bin` の `TELN` レコード1件（12バイト）で足り、`bk w` では上げられない |
| ホスト鍵と sshd の設定はどこか | **確定・実機で取得済み。** ホスト秘密鍵はバックアッププロパティ `0x03000000`（600バイト、実機で 600 バイト・PEM を確認）。`sshd_config` は nflasha10 の `/etc/ssh/sshd_config` に実在し（3,094バイト）、`PermitRootLogin no` / `PubkeyAuthentication no` / `MaxSessions 0` / SFTP 無効。`nsswitch.conf` が `passwd: files ssh` なので **NSS のバイトパッチは不要**、`/etc/passwd` を直せばよい |
| では実機でシェルが取れるのか | **実質取れた。** root でのコマンド実行が成立（`clone`+`execve` が通り、終了ステータスまで取れる）。対話端末ではなく1バッチ1往復の形 |
| 書き込みゼロで端末が取れるか | **取れない（2026-11-24 確定）。** 権限レベルは A でゲートも開いているが、端末有効化コマンド `0x00F1` のハンドラ（`libpro00.so` の `command00F1`）が **`mov w0,#1; ret` の8バイトスタブ**で、成功を返すだけで端末を作らない。A7 IV で ULOGIO の復元が必要だったのと同じ構図。[docs/CAMERA_FACTS.md](docs/CAMERA_FACTS.md) |
| では何が残っているか | **Jiritsu の `SET_FILE` が本線（2026-11-24 に経路を特定）。** 書き込んだファイルが `/tmp/jiritsu/libJit.so` だと、サービスが自分で `dlopen` する。つまり**サービスプロセス内でネイティブコードが走る**。輸送路（カテゴリ `0x1001`）は実機で読み取り成功済み。[docs/JIRITSU_SET_FILE.md](docs/JIRITSU_SET_FILE.md) |
| 任意のファイルを書けるのか | **書けない。** `SET_FILE` の書き込み先は番号で選ぶ固定表（`libJit.so` を含む5+34件）で、任意パスは読み取り側だけ。`/etc` を直接書くのではなく、`libJit.so` のコードから書くことになる |
| レベルが A でなかったら終わりか | **いいえ（2026-11-24 訂正）。** Jiritsu は `0x40` AdjustControl 経由で、全レベルのテーブルにある。実機でファイル読み取りが通っており、同じカテゴリに `SET_FILE` も定義されている。端末を経由せず `/setting/ulogio.bin`（telnet）や `/etc/ssh/sshd_config`（SSH）に届く可能性がある |

つまり「できるか」に対しては **部品は全部ある・パッチの設計も流用できる、
残るのは書き込み経路の1点** というのが現在の判定です。そしてその1点は、
**まず「自分の機体がサービス権限レベル A かどうか」を測る**ことに尽きます。

## 前提にしているもの

| 項目 | 内容 |
| --- | --- |
| 機種 | ILCE-7CM2（A7C II）、Backup region `CX89700_J1`（JP 機） |
| ファームウェア | Ver. 2.01（解析対象＝実機とも一致） |
| SoC | CXD90057（BIONZ XR、ILCE-7M4 と同系） |
| 製品クラス | `PRODUCT_MODEL_PP` |
| 既に実機で確認済み | サービスモード認証、設定バックアップ取得、`bk r` によるプロパティ読み取り |

これらは姉妹リポジトリ
[sony-a7cii-feature-research](https://github.com/soralis0912/sony-a7cii-feature-research)
で確定済みの事実です。本リポジトリはその上に「シェルアクセス」だけを積みます。

## 再現

公式アップデートは各自で入手し、[fwtool.py](https://github.com/soralis0912/fwtool.py)
の `a7cII` ブランチで展開してください。展開済みの p15 を指定すると、
本リポジトリが参照している部品の有無・サイズ・SHA-256 と、
A7 IV 6.02 の同名部品との一致を出力します。

```bash
python3 scripts/collect_shell_components.py \
  <fwtool.py>/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked \
  --json evidence/component-inventory-a7cii-201.json
```

出力例と確定値は [evidence/component-inventory-a7cii-201.json](evidence/component-inventory-a7cii-201.json)。

telnet フラグのファイルは、生成も確認もオフラインでできます。

```bash
python3 scripts/ulogio_filter_file.py --telnet 1 -o /tmp/ulogio.bin
python3 scripts/ulogio_filter_file.py --parse /tmp/ulogio.bin
```

実機側は、1本で読み取り調査を済ませてレポートを出すスクリプトがあります
（バックアップにもファイルにも書きません）。手順は
[docs/FIELD_SESSION.md](docs/FIELD_SESSION.md)。

```bash
cd ~/git/a7c2/Sony-PMCA-RE
sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/survey_readonly.py
```

権限レベルだけを測りたいときは `scripts/probe_service_level.py`。
どちらも `pmca` を `--pmca-root` → `$PMCA_ROOT` → カレントディレクトリ →
隣の `Sony-PMCA-RE` の順に探す。

## 含めないもの

Sony のファームウェア、復号済みバイナリ、カメラのバックアップ、シリアル番号、
復号鍵、抽出したプロプライエタリファイル、生成した SSH 鍵は意図的に含めていません。
記録するのはハッシュ・オフセット・手順だけです。

ライセンスは未設定です（上流の扱いは [REFERENCES.md](REFERENCES.md) を参照）。
