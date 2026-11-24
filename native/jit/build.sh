#!/bin/sh
# Build libJit.so for the camera: aarch64, Linux, glibc 2.25 (p7's runtime).
#
# Nothing here is installed for you. Pick whichever of these you already have.
#
#   1. A cross compiler on the host:
#        aarch64-linux-gnu-gcc -shared -fPIC -O1 -o libJit.so jit.c
#      (Homebrew: `brew install aarch64-elf-gcc` is the wrong one - it targets
#      bare metal, not Linux. A glibc cross toolchain is what is needed.)
#
#   2. A container, which on an Apple Silicon host runs aarch64 natively:
#        docker run --rm -v "$PWD:/src" -w /src --platform linux/arm64 \
#          gcc:12 gcc -shared -fPIC -O1 -o libJit.so jit.c
#      This pulls an image the first time.
#
#   3. clang with lld, if you have a Linux sysroot for aarch64:
#        clang -target aarch64-unknown-linux-gnu --sysroot <sysroot> \
#          -fuse-ld=lld -shared -fPIC -O1 -o libJit.so jit.c
#
# Apple clang alone cannot do it: it has no ELF linker (no ld.lld), so it can
# compile the object but not link the shared library.
set -e
cd "$(dirname "$0")"

if command -v aarch64-linux-gnu-gcc >/dev/null 2>&1; then
    aarch64-linux-gnu-gcc -shared -fPIC -O1 -o libJit.so jit.c
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker run --rm -v "$PWD:/src" -w /src --platform linux/arm64 \
        gcc:12 gcc -shared -fPIC -O1 -o libJit.so jit.c
else
    echo "no aarch64 Linux toolchain and no running Docker; see the comments" >&2
    exit 1
fi

echo "built:"
ls -l libJit.so
command -v file >/dev/null 2>&1 && file libJit.so

echo
echo "check the three symbols are exported:"
for s in CreateScriptI LoadScriptI RunScriptI; do
    if command -v nm >/dev/null 2>&1 && nm -D libJit.so 2>/dev/null | grep -q " $s$"; then
        echo "  $s ok"
    else
        printf '  %s: verify by hand (nm -D libJit.so)\n' "$s"
    fi
done
