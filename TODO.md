# TODO — シェル成立までの手順（安全な順）

危険度の低いものから。A と B は**完了**（PC のみの静的解析）。
C も PC だけで完結する。H・B2・D 以降は実機が必要で、
着手前に完全なバックアップをリポジトリ外に取る。

## H. サービス権限レベルを測る【実機・読み取りのみ・最優先】

[docs/ON_MEMORY.md](docs/ON_MEMORY.md) のとおり、**不揮発に何も書かずに
端末が取れるかはレベル A かどうかだけで決まる**。これを最初に測る。

```bash
cd ~/git/a7c2/Sony-PMCA-RE
sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/probe_service_level.py
```

- [ ] 出力の `Service level:` を記録する
- [ ] あわせて `bk r 03000000` が 600 バイト返すか確認する（ホスト鍵の確認。
      **返ってきた内容は公開しない**）
- [ ] **A だったら**、続けて `pmca-console.py serviceshell` の `shell` を試し、
      プロンプトが返るか、`grep -E '^(Uid|Gid):' /proc/self/status` が 0 かを確認する
      （書き込みは発生しない。抜けると端末は自動で無効化される）
- [ ] **B / C だったら**、オンメモリ経路は無いので A〜C の静的解析に戻る。
      あわせて `push` / `pull` / `bootrom` が実際に拒否されるかも記録する
      （`0xff01` / `0xff03` はどのレベルのテーブルにも無い、という静的判定の裏取り）

## A. telnet フラグの永続化先【完了・2026-11-24】

**`/setting/ulogio.bin`（`/dev/nflasha2` vfat rw）の `TELN` レコード。**
BK4 バックアップ経由ではない（ulogio が使う BK ID はログアドレス用の
`0x00fa0132` と `0x00fa006e` の2件だけ）。形式も確定し、
12バイトのファイル1つで足りる。
詳細： [docs/TELNET_ULOGIO.md](docs/TELNET_ULOGIO.md)、
生成： `scripts/ulogio_filter_file.py`。

- [x] `ulogio_filter_load_setting` / `_save_setting` のレコード形式を確定
- [x] ファイルパスの出所を確定（p3 initrd の `insmod_drv2` のモジュールパラメータ）
- [x] `ulogio_read_backup` に渡る BK ID を列挙（フィルタ設定は含まれない）
- [ ] 実機の既存 `/setting/ulogio.bin` を読んで保管する（**上書きする前に必須**）

## B. 公式 sshd の起動引数とホスト鍵【完了・2026-11-24】

**sshd は `/usr/sbin/sshd` を引数なしで起動**するので、設定は
コンパイル既定の `/etc/ssh/sshd_config`、つまり**書き込み可能な nflasha10**。
**ホスト秘密鍵はバックアッププロパティ `0x03000000`**（600バイト、
サブシステム `0x0300`）。詳細： [docs/SSH.md](docs/SSH.md) 5章。

- [x] `startSshd` の引数を確定
- [x] ホスト鍵のバックアッププロパティと長さを確定
- [x] アカウントロックが PAM（`pam_tally2`）であることを確認

## B2. /etc の中身を読む【実機・読み取りのみ】

nflasha10 はアップデートパッケージに入っていないので、静的解析では埋まらない。
Jiritsu の読み取り（レベル A が前提）か、シェルが取れた後に。

- [ ] `/etc/ssh/sshd_config` の有無と中身（`PermitRootLogin`、`Subsystem sftp`）
- [ ] `/etc/nsswitch.conf` の `passwd:` 行（`files ssh` か）
- [ ] `/etc/passwd` の中身（`files` が効くなら NSS 改変が不要になりうる）
- [ ] `/setting/ulogio.bin` の現物（A の最後の項目と同じ）

## C. 親子接続が PP クラスで有効か【静的には確定不能・2026-11-24】

- [x] feature manager を全数確認した。`PRM_FEATURE_MANAGER_*` は**39件だけ**で、
      親子接続・SSH・ネットワーク同期に当たる項目は**無い**。
      （あるのは `camera_parameters` / `imager_model` / `support_cfexpress` /
      `menu_item` など。ゲートはここではない）
- [x] `appFw.so` の機器記述は `<X_SSH_Support> </X_SSH_Support>` が**空のテンプレート**で、
      `Enable` / `Disable` が実行時に入る。静的には値が決まらない
- [x] infra 層に `[REQCONS-2864] [infra_wrapper_remote_parentchild] InfraRemoteParentChild not supported`
      という経路がある。つまり対応判定はここで、95MB の `appFw.so` を
      追う必要がある（費用対効果が悪い）
- [ ] **実機で観測するほうが安い。** Wi-Fi 接続時の機器記述（SCPD）を取得して
      `X_SSH_Support` の値を見る、またはメニューに親子接続の項目があるかを見る

## D. Jiritsu の読み取りプローブを実機で通す【実機・読み取りのみ】

姉妹リポジトリの残タスク B と同じ。これが通らないと経路2は始まらない。
**前提**：Jiritsu は `0xff00` TestMode 経由で、そのテーブルはレベル A にしか無い。
H でレベル A が出ていなければ、ここは通らない見込み。

- [ ] `a7cii_jiritsu_readonly_probe.py` を実行し、
      `/usr/share/pmbp/DeviceInfo.xml` が 517 バイト・既知のハッシュで返るか確認する
- [ ] 返ったら、`../../` のパス解決が実際に効いていることを別パスでも確認する

## E. 書き込み側を揮発領域で試す【実機・書き込み】

D が通ってから。**最初の書き込み先は `/tmp` 配下など再起動で消える場所に限る。**

- [ ] `@JIRITSU_SET_FILE` / `SET_FILE2` のコマンド形式を特定する
- [ ] `/tmp` 配下に小さなファイルを書き、`GET_FILE2` で読み戻して一致を確認する
- [ ] `dlopen` される名前（`libtestcmd.so` ほか）の探索パスを確認する
- [ ] 無害な `.so`（初期化で1行ログを出すだけ）を読み込ませ、EUID を確認する

## F. シェルを取る【実機】

H でレベル A が出ていればそちらが先（書き込みゼロ）。
E で native 実行が取れた場合は：

- [ ] `ulogio telnet up` 相当を実行し、再起動後に TCP 23 が開くか確認する
      （閉じたネットワークで。平文・ログイン無しのため公衆無線に繋がない）
- [ ] 端末でコマンドが返ること、`grep -E '^(Uid|Gid):' /proc/self/status` が
      すべて 0 であることを確認する。marker やハンドシェイクだけでは成功としない

## G. SSH を恒久化する【実機】

**まず B2 をやること。** sshd の設定とアカウントは書き込み可能な nflasha10
（`/etc`）側にあるので、**p15 を書き換えずに済む可能性がある**。
`/etc/passwd` と `/etc/ssh/sshd_config` で足りるなら、以下の p15 改変は不要。

p15 改変が必要だと分かった場合のみ、F まで到達し、かつ書き戻し手段と
復旧手段が確立してから：

- [ ] 自機の `libnss_ssh.so.2` の SHA-256 が
      `21c29cad…f051e4` と一致することを確認する
- [ ] [docs/SSH.md](docs/SSH.md) の改変表を適用した候補を**オフラインで**作る
- [ ] `bootin.elf` のフックを A7C II 側の寸法で再導出する
- [ ] 書き込み後は**独立した完全回読**を行ってから起動する
- [ ] 復旧手段（改変前の自機 p15）を必ず手元に残す

## I. オンメモリ sshd を立てる【実機・端末が取れた後】

[docs/ON_MEMORY.md](docs/ON_MEMORY.md) 5章の設計。不揮発には何も残さない。

- [ ] `/bin/sh` が実在するか、無ければ何を使うかを確認する
- [ ] `/tmp_wbshd` が tmpfs でマウントされていることを実機で確認する
- [ ] `/tmp_wbshd/ssh` に設定・ホスト鍵・`ssh_name_password` を作る
- [ ] まず `internal-sftp` だけで root 接続を確認する（NSS 改変なし）
- [ ] 対話シェルが必要なら、`libnss_ssh.so.2` の複製を `/tmp_wbshd/lib` に置き、
      `LD_LIBRARY_PATH` で差し替えて起動する
- [ ] 電源を入れ直し、**何も残っていない**ことを確認する

## やらないこと

- Fastboot / BootROM（[docs/WRITE_PATHS.md](docs/WRITE_PATHS.md) 経路4）は、
  A7C II の配線と起動ストラップが確認できるまで着手しない。
- カメラのバックアップ、シリアル番号、生成した鍵、Sony のバイナリは
  リポジトリに入れない。
