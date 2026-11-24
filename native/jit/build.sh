#!/bin/sh
# Build libJit.so for the camera (aarch64 Linux).
#
# Two sources, two toolchains:
#
#   jit_nolibc.c   no libc at all, raw syscalls. Builds with the bare-metal
#                  toolchain from Homebrew core:
#                      brew install aarch64-elf-gcc
#                  The result has no DT_NEEDED, so the camera's glibc version
#                  cannot be a problem. This is the default.
#
#   jit.c          the readable libc version. Needs a glibc cross toolchain:
#                      brew tap messense/macos-cross-toolchains
#                      brew trust messense/macos-cross-toolchains   # third-party tap
#                      brew install aarch64-unknown-linux-gnu
#                  Homebrew refuses to load that tap's formulae until it is
#                  trusted, which is a decision for whoever runs this. If it is
#                  installed, this script prefers it.
#
# Apple clang cannot do either: no ELF linker (no ld.lld) is installed with it.
set -e
cd "$(dirname "$0")"
PATH="/opt/homebrew/bin:$PATH"
export PATH

if command -v aarch64-unknown-linux-gnu-gcc >/dev/null 2>&1; then
    echo "building jit.c with the glibc cross toolchain"
    aarch64-unknown-linux-gnu-gcc -shared -fPIC -O1 -Wall -o libJit.so jit.c
elif command -v aarch64-elf-gcc >/dev/null 2>&1; then
    echo "building jit_nolibc.c with aarch64-elf-gcc (no libc)"
    aarch64-elf-gcc -shared -fPIC -nostdlib -O1 -Wall -o libJit.so jit_nolibc.c
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "building jit.c in a linux/arm64 container"
    docker run --rm -v "$PWD:/src" -w /src --platform linux/arm64 \
        gcc:12 gcc -shared -fPIC -O1 -o libJit.so jit.c
else
    echo "no aarch64 toolchain and no running Docker; see the comments above" >&2
    exit 1
fi

ls -l libJit.so
exec ./check.sh libJit.so
