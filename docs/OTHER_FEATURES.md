# SSH 以外の機能：A7C II で成立しそうなもの／しなさそうなもの

A7 IV 系の公開手法と、A7C II 2.01 の実測（BKID 6,450件の一覧と p15 の中身）を
突き合わせた見通し。数字の出典は姉妹リポジトリの
`evidence/bkid-inventory-a7cii-201.json`。

| 機能 | A7C II での裏づけ | 見通し |
| --- | --- | --- |
| シャッター角表示 | `0x02cf1700 MODE_SHUTTER`（既定 `00`）、`0x02cf1702 SHUTTER_ANGLE`（`10`）。実機 `bk r` 一致 | **プロパティのみで試せる。** 姉妹リポジトリの実験1がこれ |
| Log 撮影 | `0x02cf101d LOG_SHOOTING`、`0x02cf19f0 STILL_LOG_SHOOTING` | 同上。プロパティ実験の候補2 |
| カスタム LUT | `0x02cf1021 EMBED_LUT_FILE`、`0x02cf102d SELECT_LUT`、`0x02cf1030 APPLY_LUT`、`0x02cf1983 IMPORT_LUT_HQ_CONVERSION`、ユーザー LUT **50スロット**（`IS_EXIST_USER_LUT0`〜`49`） | プロパティで入口が開く可能性あり。LUT の取り込みそのものは別途 |
| デスクイーズ表示 | `0x02cf1961 DE_SQUEEZE_DISP`、`0x02cf1193`、`0x02cf1964` | 同上。候補3 |
| 8K / 高ビットレート記録 | `0x02cf020c`〜 `MOVIE_RECORD_SETTING_XAVC_HS_8K_*`、`REC_FRAME_RATE_XAVC_HS_8K` が**定義として存在** | **期待薄。** `appFw.so` は機種共通で、上位機の定義が残っているだけ。センサ読み出しと feature manager の両方が壁 |
| オープンゲート（3:2 全画素） | `0x02cf01fc ASPECT_RATIO`、`MOVIE_REC_ASPECT_XAVC` 系 | A7 IV の open-gate 実装は AP/CP 側のコード改変で、プロパティだけでは届かない。p15 書き換え前提 |
| カスタムシャッター音 | `BKID_APP_BEEP_SOUND_ID_SHUTTER_KASHA_CONTINUOUS_3/4`、`EXTERN_MENU_CUSTOM_BEEP_ID_STARTUP`、音源は p8 の `SysSound.bin` | 定義はある。音源差し替えはパーティション書き込みが必要 |
| 互換バッテリー / 他社レンズ AF / AWB 優先 | BKID 一覧に該当名**なし**（0件） | A7 IV ではコード側のパッチで、A7C II ではまだ手がかりなし |
| ファームウェア版数の表示操作 | 更新系ライブラリは p15 側（[WRITE_PATHS.md](WRITE_PATHS.md) 経路3） | 書き込み経路が確立してから |

## 読み方

- 「BKID に定義がある」＝ファームウェア内に名前と既定値がある、までの意味。
  実機で読めるか、書いて挙動が変わるかは別。姉妹リポジトリの実機実験で確かめる。
- 「定義があるのに機能が無い」ケースが多いのは、`appFw.so` が α 系で共通であり、
  機種差は feature manager と製品クラス（A7C II は `PRODUCT_MODEL_PP`）で
  決まるため。クラス側で `NONE` のものは、プロパティを立てても出ない前提で見る。
- 本リポジトリの主題はシェルなので、上の表のうちプロパティだけで試せるものは
  姉妹リポジトリ側に任せ、ここでは**書き込み経路が必要なもの**だけを追う。
