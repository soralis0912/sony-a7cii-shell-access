# 参照元と帰属

本リポジトリは ILCE-7CM2（A7C II）について**新規に**書いたもので、
どのリポジトリの fork でもない。Sony のファームウェア、バイナリ、鍵、
カメラのバックアップは一切含まない。記録しているのはハッシュ・オフセット・手順のみ。

## 直接参照している研究

- [soralis0912/sony-a7cii-feature-research](https://github.com/soralis0912/sony-a7cii-feature-research)
  — 姉妹リポジトリ。ILCE-7CM2 2.01 の展開、製品クラス `PRODUCT_MODEL_PP` の確定、
  BKID 6,450件の一覧、サービスモード接続とバックアップ取得の実績。
  本リポジトリの前提事実はすべてここから。
- [soralis0912/fwtool.py](https://github.com/soralis0912/fwtool.py/tree/a7cII)
  （`a7cII` ブランチ）— CXD90057 / ILCE-7CM2 対応のファームウェア展開。
  上流は DavidBuchanan314 の `a7iv` ブランチ、さらに上流は ma1co/fwtool.py。
- [ma1co/Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE)
  — USB サービスモードの通信とバックアップシェル（`bk r` / `bk w` / `bk s`）。

## 比較対象として参照した A7 IV（ILCE-7M4）の公開成果

A7C II の部品が「どこまで同じか」を判定するための基準として参照した。
これらの成果は原著者のもので、本リポジトリはその数値（ハッシュ・オフセット）を
**比較のために引用**している。

- [Erlla/sony-a7m4-custom-firmware](https://github.com/Erlla/sony-a7m4-custom-firmware)
  — `methods/09-shell-access` の SSH / Telnet / UART 手法と
  `reference-layout.json` の構成要素ハッシュ、`no-fastboot-install` の
  更新系パッチ原理。ライセンスは GPLv3（履歴上の MIT 部分と第三者構成要素は各々のライセンス）。
- [DavidBuchanan314/ILCE-7M4-RE](https://github.com/DavidBuchanan314/ILCE-7M4-RE)
  — BootROM / Fastboot、RP2040、Cetus/SPI の参考。
- [DavidBuchanan314/Sony-ILCE-7M4-Linux](https://github.com/DavidBuchanan314/Sony-ILCE-7M4-Linux)
  — プラットフォーム参考。
- [ArcaneLantern/a7iv-open-gate-test](https://github.com/ArcaneLantern/a7iv-open-gate-test)
  — オープンゲート検証（本リポジトリでは見通しの比較にのみ使用）。
- [leogenot/sony-a7iv-feature-research](https://github.com/leogenot/sony-a7iv-feature-research)
  — 姉妹リポジトリの雛形。

## ライセンス

未設定。A7 IV 手法の文章・コードを取り込む場合は GPLv3 の条件に従う必要があるため、
本リポジトリでは**数値の引用と出典明記に留め、コードは移植していない**。
公開する場合はライセンスを決めてから。
