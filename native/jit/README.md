# native/jit — 最小の `libJit.so`

カメラのサービスプロセス内でコードを走らせるための最小の共有ライブラリ。
読み込み側の実装と根拠は [../../docs/JIRITSU_SET_FILE.md](../../docs/JIRITSU_SET_FILE.md)。

| ファイル | 内容 |
| --- | --- |
| `jit.c` | コンストラクタで `/tmp/jiritsu/jit_hello.txt` に pid/uid/euid を書く。`CreateScriptI` / `LoadScriptI` / `RunScriptI` をエクスポートし、`CreateScriptI` は非ゼロを返す |
| `build.sh` | aarch64 Linux 向けにビルドする。クロスコンパイラか Docker のどちらかを使う |

**このリポジトリにバイナリは置かない**（`.gitignore` が `*.so` を除外している）。
各自でビルドすること。

## ビルド環境について

ホストは Apple Silicon の macOS で、**Apple clang だけではビルドできない**
（ELF リンカが無い。`ld.lld` が入っていない）。選択肢は3つ：

1. glibc 向けクロスコンパイラ（`aarch64-linux-gnu-gcc`）
2. **Docker**。Apple Silicon なら `--platform linux/arm64` が native で動くので
   `gcc:12` イメージでそのままビルドできる。初回はイメージの取得が必要
3. clang + `ld.lld` + aarch64 の sysroot

`build.sh` は 1 → 2 の順に自動で選ぶ。どちらも無ければ理由を出して終了する。

## 実機で使うときの順番

1. ビルドして `nm -D libJit.so` で3シンボルを確認する
2. `SET_FILE`（カテゴリ `0x1001` / コマンド `0x4007`）で**番号2・モード0**として送る
3. 戻り値を確認する（失敗コードは
   [../../docs/JIRITSU_SET_FILE.md](../../docs/JIRITSU_SET_FILE.md)）
4. `SET_FILE_PATH` + `GET_FILE2` で `/tmp/jiritsu/jit_hello.txt` を読み戻す。
   **読めたら、サービスプロセス内でコードが走ったことの証明になる**
5. 失敗した場合は `/tmp/jiritsu/jit.log` を読む。各段階が
   `[JIT] libJit_so dll open B.` のような文字列で記録されている

最初の1回は**何も変更しない**こと。確認するのは「実行できたか」だけ。
`/etc` の書き換えはその次。
