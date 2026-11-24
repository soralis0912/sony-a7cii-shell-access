# TODO — シェル成立までの手順（安全な順）

危険度の低いものから。A〜C は **PC だけで完結**（カメラ不要）。
D 以降は実機が必要で、着手前に完全なバックアップをリポジトリ外に取る。

## H. サービス権限レベルを測る【実機・読み取りのみ・最優先】

[docs/ON_MEMORY.md](docs/ON_MEMORY.md) のとおり、**不揮発に何も書かずに
端末が取れるかはレベル A かどうかだけで決まる**。これを最初に測る。

```bash
cd ~/git/a7c2/Sony-PMCA-RE
sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/probe_service_level.py
```

- [ ] 出力の `Service level:` を記録する
- [ ] **A だったら**、続けて `pmca-console.py serviceshell` の `shell` を試し、
      プロンプトが返るか、`grep -E '^(Uid|Gid):' /proc/self/status` が 0 かを確認する
      （書き込みは発生しない。抜けると端末は自動で無効化される）
- [ ] **B / C だったら**、オンメモリ経路は無いので A〜C の静的解析に戻る。
      あわせて `push` / `pull` / `bootrom` が実際に拒否されるかも記録する
      （`0xff01` / `0xff03` はどのレベルのテーブルにも無い、という静的判定の裏取り）

## A. telnet フラグの永続化先を確定する【PC のみ】

`libosal_ulogio.so` の `TELN` タグ（[docs/TELNET_ULOGIO.md](docs/TELNET_ULOGIO.md)）が
ファイル由来なのかバックアップ由来なのかを決める。

- [ ] `ulogio_filter_load_setting`（VA `0x6010`）の呼び出し元を特定する
- [ ] `ulogio_get_filterfile`（`.data` の `0x19ad8`）に入るパス文字列を、
      `bin/ulogio` / `bin/bootin.elf` 側から特定する
- [ ] `ulogio_read_backup`（VA `0x7428`）に渡る BKID 定数を列挙する
- [ ] 結論を docs に記録する。**バックアップ由来なら `bk w` だけで
      telnet が上がる可能性があるので、その時点で優先度が全部入れ替わる**
      （ただしこれは不揮発への書き込みで、オンメモリではない）

## B. 公式 sshd の起動引数を特定する【PC のみ】

- [ ] `libInfraSSHManager.so` の `startSshd` が組む引数列を読む
      （`SSHD_START_CMD` の参照元）
- [ ] 設定ファイルを使うのか、引数だけなのかを決める
- [ ] `PermitRootLogin` / `AllowUsers` / `Subsystem sftp` の有無を記録する
- [ ] ホスト鍵がバックアップのどのプロパティに入るか（`updateBackupKey`）を特定する

## C. 親子接続が PP クラスで有効かを判定する【PC のみ】

- [ ] feature manager 側に親子接続 / SSH の可否フラグがあるか再確認する
- [ ] `X_SSH_Support` を出す条件（`appFw.so` の機器記述生成箇所）を読む

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

## G. SSH を恒久化する【実機・p15 書き換えを伴う】

F まで到達し、かつ書き戻し手段と復旧手段が確立してから。

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
