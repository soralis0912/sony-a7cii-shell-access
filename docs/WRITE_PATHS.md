# 書き込み・実行経路：ここが唯一の関門

シェル成立の設計（[SSH.md](SSH.md) / [TELNET_ULOGIO.md](TELNET_ULOGIO.md)）は揃っている。
足りないのは、その変更をカメラに載せる経路。危険度の低い順に並べる。

## 経路1：BK4 バックアッププロパティ（確立済み・最も安全）

- 状態：**サービスモード認証と `bk r` は実機で成功済み**（姉妹リポジトリ）。
  `bk w` / `bk s` は未実験。
- できること：プロパティ単位の読み書き。ファイルシステムには触れない。
- シェルとの関係：
  - 親子接続の SSH 関連プロパティ（`0x02cf184a`〜、`0x02cf18bb` ほか）を立てて
    公式 sshd が起きるかを試せる。
  - `TELN`（telnet フラグ）がバックアップ由来なら、これだけで telnet が上がる。
- 制約：`libnss_ssh.so.2` のシェルは `/bin/false` のままなので、
  **SSH でログインできても端末にはならない**。SFTP サブシステムが公式設定に
  入っていれば、ファイル読み書きだけは取れる可能性がある（未確認）。
- 作法：1プロパティずつ。記録 → 書換 → `bk s` → 電源断（バッテリー10秒抜き）
  → 確認 → 復旧。

## 経路2：Jiritsu のファイル操作（有望・未検証）

`lib/libsencore.so` が持つコマンド名（実測）：

```text
@JIRITSU_START        @JIRITSU_MODE          @JIRITSU_DEBUG
@JIRITSU_SET_FILE_PATH
@JIRITSU_GET_FILE     @JIRITSU_GET_FILE2     @JIRITSU_GET_FILELIST
@JIRITSU_GET_FILE_HASH
@JIRITSU_SET_FILE     @JIRITSU_SET_FILE2
@JIRITSU_FILE_DELETE  @JIRITSU_FILE_DELETE2
@JIRITSU_MOUNT        @JIRITSU_FORMAT        @JIRITSU_FIRMUP
@JIRITSU_COMPARE_MEDIA @JIRITSU_FACTORY
```

同じライブラリに `dlopen` と、読み込み対象になりうる名前
`libpro%02X.so`、`libtestcmd.so`、`libtestcmd_scn.so`、`libSnr.so` がある。

- 読み側：`SET_FILE_PATH` に `../../` を含めると `/tmp/jiritsu` 配下から
  Linux ルートへ抜けられる、という仮説まで（姉妹リポジトリの
  `a7cii_jiritsu_readonly_probe.py`。**未実行**）。
- 書き側：`SET_FILE` / `SET_FILE2` が同じパス解決を使うなら、
  任意パスへの書き込みになる。
- 実行側：`dlopen` される名前のいずれかを書き込めれば、
  認証済みサービスプロセス内で native コードが走る。A7 IV で使われている
  「一時 `.so` をサービスプロセスに読み込ませて EUID 0 で実行」と同種。
- これが通れば **p15 を書き換えずに**、
  `ulogio telnet up` 相当の操作や `/tmp_network/ssh/*` の配置までできる。
- 危険度：書き込みは実機のファイルを変える。まず読み取りプローブで
  パス解決の挙動を確認し、書き込みは `/tmp` 配下など揮発領域から試す。

## 経路3：更新パッケージの署名検証を無効化（重い・要再導出）

A7 IV では p1（更新システム）の署名検証と版数判定を潰して、
改変 `BODYDATA.DAT` をメニューからインストールできるようにしている。
**A7C II ではこの表がそのまま使えない。**

| 点 | A7 IV | A7C II 2.01 |
| --- | --- | --- |
| p1 パーティションイメージ | パッケージに含まれる | **含まれない** |
| 更新系の置き場 | p1 initrd の `usr/lib/*` | `updater.img` と p15 内 `bin/udtrbody.bin` |
| 対象ライブラリ名 | `libsdfileinputupdaterapi.so` ほか | p15 に `libfileinputupdaterapi.so`、`libcryptfileinputupdaterapi.so`、`libupdatercorecommon.so`、`libupdaterufp.so` |
| シンボル | 手法側に関数名の記載あり | **除去済み**（`VerifySignature` 等の名前は残っていない） |

つまり同じ考え方は使えるが、検証関数の特定とオフセット導出を
A7C II 向けに一からやる必要がある。経路2が通るなら、そちらが先。

## 経路4：Fastboot / BootROM（未確認・最も重い）

A7 IV は BootROM 経由で fastboot に入り、パーティションを直接書く
（Multi 端子 + RP2040 + Cetus ブリッジ）。SoC は A7C II も同じ **CXD90057** なので
上流の成果が効く見込みはあるが、**A7C II の Multi 端子配線と起動ストラップは
未確認**。文鎮化の危険が最も高く、最初に試す経路ではない。

## 判断

優先順位は **経路1（情報収集）→ 経路2（読み取り→書き込み）→ 経路3 → 経路4**。
経路2が通れば、シェル取得までファームウェア書き換えなしで到達しうる。
いずれの経路でも、着手前に完全なバックアップを取り、リポジトリ外に保管する。
