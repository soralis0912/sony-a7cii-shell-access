# 実機セッションの手順書

家で実機を触るとき、**上から順にこれだけやれば済む**ようにまとめたもの。
危険度の低い順で、最初の2段階は**カメラに何も書き込まない**。

## 0. 準備

- [ ] バッテリーを十分に充電する（純正を使う）
- [ ] メニュー → セットアップ → USB → **USB接続モード：マスストレージ**
- [ ] PC に**直結**する（ハブを挟まない）。写真アプリや画像取り込みを閉じる
- [ ] 設定バックアップは 2026-11-24 に取得済み（2,390,264 バイト、
      SHA-256 `27ec1eb1…6d1b916`）。**リポジトリ外に置いたまま**にする。
      手元に無ければ先に取り直す（姉妹リポジトリの `a7cii_read_backup.py`）

## 1. 一括調査（読み取りのみ・5分）

これ1本で、権限レベル・主要プロパティ・ホスト鍵の有無がまとめて分かり、
さらに **Jiritsu 経由で `/etc/ssh/sshd_config` や `/setting/ulogio.bin` を
実際に読んで**レポートファイルに落とす（Jiritsu の読み取りは
2026-11-24 に実機で確認済みの経路。書き込み系コマンドは一切送らない）。

```bash
cd ~/git/a7c2/Sony-PMCA-RE
sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/survey_readonly.py
```

- [ ] 出てきた `a7cii-survey-<日付>.txt` をそのまま貼る
- 途中で「マスストレージに入り直せ」と言われたら、背面の中央ボタンを押して
      接続し直す（PMCA のサービスモード切替は何度か往復する）

**書き込みは発生しない。** 唯一状態に触るのは「端末オフ」を送る1回で、
これはカメラが既にそう思っている値。

## 2. 分岐：レポートの `service level:` を見る

### レベル A だった場合 → そのままシェルを試す（書き込みゼロ）

```bash
cd ~/git/a7c2/Sony-PMCA-RE
sudo ./venv/bin/python ./pmca-console.py serviceshell
```

プロンプトが出たら：

```text
> info
> shell
```

端末が開いたら、**読み取りだけ**を順にやる（どれも書き込まない）：

```sh
grep -E '^(Uid|Gid):' /proc/self/status
mount
ls -l /etc/ssh/
cat /etc/ssh/sshd_config
cat /etc/nsswitch.conf
cat /etc/passwd
ls -l /setting/ulogio.bin /cp/filter.bin
cat /proc/osal/ulogio
ls -l /bin/sh /bin/busybox /usr/sbin/sshd
ls -ld /tmp_wbshd /tmp_network/ssh
```

- [ ] 出力を全部貼る。特に `sshd_config` と `nsswitch.conf` と `mount`
- [ ] `Ctrl+C` で端末を抜け、`exit` でシェルを閉じる
      （抜けると端末は自動で無効化され、カメラは元の状態に戻る）

この出力で、**root SSH にファームウェア改変が要るのか要らないのか**が決まる。
`/etc` が書き込み可能で `sshd_config` を置き換えられるなら、p15 は触らない。

### レベル B または C だった場合 → USB 端末は諦めて Jiritsu で進む

端末ゲートはレベル A 限定なので `shell` は使えない。
ただし **Jiritsu は権限レベルに依らず通る**（`0x40` AdjustControl 経由）。
レポートの「## 5. file reads through Jiritsu」で `/etc/ssh/sshd_config` や
`/etc/passwd` が返っていれば、それがそのまま次の判断材料になる。

- [ ] レポートの5章を貼る（`/etc/passwd` の hash 欄は伏せる）
- [ ] 対照の `DeviceInfo.xml` が「matches the firmware file」と出ているか確認する

## 3. プロパティ実験（レベルに関係なくできる・1件ずつ）

**不揮発に書き込む**ので、1件ずつ、必ず復旧まで1サイクルで終わらせる。
2件を同時に変えない。

### 実験1：デスキーズ表示 `0x02cf1961` を `00` → `01`

```bash
cd ~/git/a7c2/Sony-PMCA-RE
sudo ./venv/bin/python ./pmca-console.py serviceshell
```

```text
> bk r 02cf1961
00
> bk w 02cf1961 01
> bk r 02cf1961
01
> bk s
> exit
```

- [ ] カメラの電源を切り、USB を外し、**バッテリーを10秒抜いて**から戻して起動
- [ ] 動画モードのメニューに「デスキーズ表示」系の項目が出たか確認する
- [ ] **復旧**：`bk w 02cf1961 00` → `bk s` → `exit` → 同じ電源サイクル →
      `bk r 02cf1961` が `00` に戻ったことを確認
- [ ] 結果を記録する。出なかった場合も「反映されなかった」という結果

### 実験2：シャッター角モード `0x02cf1700` を `00` → `01`

同じ手順で。動画モードのシャッター表示が速度（1/xxx）から角度（xxx°）に
変わるかを見る。復旧も同じ。

### 実験3以降

`0x02cf101d` LOG_SHOOTING、`0x02cf1193` EXTERN_DE_SQUEEZE_DISP。
いずれも同じ1サイクル。

## 4. やらないこと（この段階では）

- `/setting/ulogio.bin` の書き込み（telnet 有効化）。
  **先に現物を読んで保管してから**。レベル A のシェルで
  `cp /setting/ulogio.bin /tmp_wbshd/` ではなく、まず `cat` して内容を貼る
- p15（`/usr`）の書き換え。読み取り専用マウントで、そもそも実行中には当たらない
- ホスト鍵（`bk r 03000000`）の**中身を貼ること**。長さとハッシュだけでよい
- 2件以上のプロパティを同時に変えること

## 5. 記録と公開の線引き

| 貼ってよい | 貼らない |
| --- | --- |
| 権限レベル、`info` の Model / Backup region | シリアル番号 |
| プロパティの値（`bk r` の hex） | ホスト鍵の中身（`0x03000000`） |
| `sshd_config`、`nsswitch.conf`、`mount`、`/proc/osal/ulogio` | `/etc/passwd` の hash 欄（`x` 以外が入っていたら伏せる） |
| ファイルの長さと SHA-256 | バックアップファイル本体 |

## 6. 何か起きたとき

- メニューが出ない・挙動が変わった → 変更したプロパティを元の値に戻して
  `bk s`、電源サイクル
- 起動しない → **コールドブート**（バッテリーを抜いて10秒）。
  本手順書の範囲（プロパティ1件とシェルの読み取り）では、
  ファームウェアもパーティションも書き換えていないので、
  バックアップからの復旧手段が残っている
- サービスモードに入れない → USB を抜き差しし、マスストレージを選び直す
