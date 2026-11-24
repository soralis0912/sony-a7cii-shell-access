# native/jit — 最小の `libJit.so`

カメラのサービスプロセス内でコードを走らせるための最小の共有ライブラリ。
読み込み側の実装と根拠は [../../docs/JIRITSU_SET_FILE.md](../../docs/JIRITSU_SET_FILE.md)。

| ファイル | 内容 |
| --- | --- |
| `jit_nolibc.c` | **既定。libc を一切使わず**、生のシステムコールで `/tmp/jiritsu/jit_hello.txt` に pid/uid/euid を書く。`DT_NEEDED` が無いので**カメラの glibc 版数が問題になりえない** |
| `jit.c` | 同じことを libc で書いたもの。読みやすいが glibc 向けクロスツールチェインが必要 |
| `build.sh` | 使えるツールチェインを自動で選んでビルドし、`check.sh` を実行する |
| `check.sh` | 出来たものがカメラで読めるかを検証する（ELF 種別、3シンボル、`INIT_ARRAY`、要求 glibc、未定義シンボル） |

## ビルド済みの実測（2026-11-24）

`aarch64-elf-gcc`（Homebrew core）で `jit_nolibc.c` をビルドした結果：

| 項目 | 値 |
| --- | --- |
| サイズ | 3,328 バイト |
| 種別 | ELF64 / little endian / **DYN（共有オブジェクト）** / AArch64 |
| エクスポート | `CreateScriptI` / `LoadScriptI` / `RunScriptI` すべて `T` |
| `DT_INIT_ARRAY` | あり。`R_AARCH64_RELATIVE` 1件で `jit_boot` を指している |
| `DT_NEEDED` | **なし** |
| 未定義シンボル | **なし** |

構造上の準備は完了。**実機で `dlopen` が通るかは未検証。**

**このリポジトリにバイナリは置かない**（`.gitignore` が `*.so` を除外している）。
各自でビルドすること。

## ビルド環境について

ホストは Apple Silicon の macOS。**Apple clang だけではビルドできない**
（ELF リンカが無い。`ld.lld` が入っていない）。

実際に使った構成：

```bash
brew install aarch64-elf-gcc        # Homebrew core、信頼済み、bottle
./build.sh                          # jit_nolibc.c をビルドして check.sh を実行
```

`aarch64-elf-gcc` はベアメタル向けで glibc を持たないが、
`jit_nolibc.c` は libc を使わないので問題にならない。むしろ
**`DT_NEEDED` が無くなるのでカメラの glibc 版数に依存しなくなる**という利点がある。

libc 版（`jit.c`）を使いたい場合は glibc 向けクロスツールチェインが要る：

```bash
brew tap messense/macos-cross-toolchains
brew trust messense/macos-cross-toolchains     # 第三者タップの信頼が必要
brew install aarch64-unknown-linux-gnu
```

Homebrew は第三者タップの formula を `brew trust` するまで読み込まない。
これはタップのビルドコードを信頼するという判断なので、各自で決めること。
`build.sh` は glibc 版が入っていればそちらを優先する。

## glibc のバージョンに注意

カメラのルートは **glibc 2.25**（p7 の `lib/libc-2.25.so`）で、Sony 自身の
ライブラリは `GLIBC_2.17` のシンボルを要求している。新しい glibc で
ビルドしたものは、存在しないシンボルバージョンを要求して**読み込みに失敗する**。
しかもその失敗はプロトコル側の問題のように見えるので、先に潰しておく：

```bash
./check.sh          # 3シンボル＋要求 glibc が 2.25 以下かを確認
```

`aarch64-elf-gcc`（homebrew-core）はベアメタル向けで glibc が無いため、
`jit.c` をそのままビルドできない。glibc 向けのクロスツールチェイン
（`messense/macos-cross-toolchains` の `aarch64-unknown-linux-gnu`）を使う。

## 実機で使うときの順番

1. ビルドして `./check.sh` を通す
2. `SET_FILE`（カテゴリ `0x1001` / コマンド `0x4007`）で**番号2・モード0**として送る
3. 戻り値を確認する（失敗コードは
   [../../docs/JIRITSU_SET_FILE.md](../../docs/JIRITSU_SET_FILE.md)）
4. `SET_FILE_PATH` + `GET_FILE2` で `/tmp/jiritsu/jit_hello.txt` を読み戻す。
   **読めたら、サービスプロセス内でコードが走ったことの証明になる**
5. 失敗した場合は `/tmp/jiritsu/jit.log` を読む。各段階が
   `[JIT] libJit_so dll open B.` のような文字列で記録されている

最初の1回は**何も変更しない**こと。確認するのは「実行できたか」だけ。
`/etc` の書き換えはその次。
