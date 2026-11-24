# Sony A7C II シェルアクセス調査（SSH / Telnet / サービス端末）

自己責任で利用してください。本リポジトリの利用による損害について、作者は責任を負いません。
ファームウェアの書き換えはカメラを恒久的に起動不能にし、撮影データ・調整値・設定を
破壊しうる操作です。保証・修理・公式アップデートにも影響します。

Sony **ILCE-7CM2**（A7C II）Ver. **2.01** で root シェル（SSH / Telnet / サービス USB 端末）が
成立しうるかを、公式アップデートの展開結果とサービスモードの実測から判定するための
リポジトリです。**ここにあるのは静的解析による可否判定と検証計画で、実機での
シェル取得は未達成**です。

- 判定の要約： [docs/FEASIBILITY.md](docs/FEASIBILITY.md)
- **オンメモリ（不揮発に書かずに）取れるか**： [docs/ON_MEMORY.md](docs/ON_MEMORY.md)
- SSH（既存 sshd の再利用）： [docs/SSH.md](docs/SSH.md)
- Telnet / ulogio： [docs/TELNET_ULOGIO.md](docs/TELNET_ULOGIO.md)
- 書き込み・実行経路（ここが本当の関門）： [docs/WRITE_PATHS.md](docs/WRITE_PATHS.md)
- SSH 以外の機能： [docs/OTHER_FEATURES.md](docs/OTHER_FEATURES.md)
- 次にやること： [TODO.md](TODO.md)
- 参照元と帰属： [REFERENCES.md](REFERENCES.md)

## 結論（2026-11-24 時点）

| 問い | 答え |
| --- | --- |
| A7C II に SSH サーバは載っているか | **載っている。** `/usr/sbin/sshd` 本体、`ssh-keygen`、ホスト鍵生成スクリプト、セッション監視、アカウントロック記録、NSS モジュール、`libssh2` がすべて 2.01 の p15 に入っている |
| それは何のための sshd か | 公式機能「親子（マルチカメラ）接続」のサーバ側。機器記述に `X_SSH_Support` / `X_SSH_QRSetupSupport`、バックアップに子機19スロット分の `BKID_APP_PARENT_CHILD_SERVER_CAMERA_SSH_*` がある |
| A7 IV の SSH 手法はそのまま効くか | **要の1ファイルは完全に同一。** `lib/libnss_ssh.so.2`（10,192 バイト）は A7 IV 6.02 と SHA-256 が一致するので、公開されている8箇所のワードパッチと3つの文字列スロットがバイト単位でそのまま当たる |
| Telnet はどうか | A7 IV 6.02 より条件が良い。`libosal_ulogio.so` に telnetd の実装（`ulogio_telnetd_init` / `_mainloop` / `ulogio_filter_set_telnet`）が**残っている**ので、旧版からの移植が不要 |
| では実機でシェルが取れるのか | **まだ取れない。** ただし恒久的な書き込みを伴わない経路が1つ見つかった（下記） |
| 書き込みゼロで端末が取れるか | **サービス権限レベル A（`adjCodeLevel == 3`）なら取れる見込み。** 端末ゲートはレベル A のときだけ開き、カメラのコンソールには初めから `ash --login` が走っている。レベル B/C だと TestMode も使えず行き止まり。判定は `scripts/probe_service_level.py`（読み取りのみ）。詳細は [docs/ON_MEMORY.md](docs/ON_MEMORY.md) |

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

実機側は、サービスモードで権限レベルだけを測る読み取り専用プローブがあります
（バックアップにもファイルにも書きません）。

```bash
cd ~/git/a7c2/Sony-PMCA-RE
sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/probe_service_level.py
```

## 含めないもの

Sony のファームウェア、復号済みバイナリ、カメラのバックアップ、シリアル番号、
復号鍵、抽出したプロプライエタリファイル、生成した SSH 鍵は意図的に含めていません。
記録するのはハッシュ・オフセット・手順だけです。

ライセンスは未設定です（上流の扱いは [REFERENCES.md](REFERENCES.md) を参照）。
