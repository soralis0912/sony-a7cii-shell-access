#!/bin/sh
# Check a built libJit.so against what the camera can actually load.
#
# The camera's root filesystem carries glibc 2.25 (p7: lib/libc-2.25.so), and
# the libraries Sony ships there require GLIBC_2.17 symbols. A cross toolchain
# built against a newer glibc can emit references to symbol versions that do
# not exist on the camera - the library would then fail to load, and the
# failure would look like a protocol problem rather than a build problem.
#
# This checks the three exports are present and that nothing requires a glibc
# newer than 2.25.
set -e
cd "$(dirname "$0")"
LIB=${1:-libJit.so}
NM=${NM:-aarch64-unknown-linux-gnu-nm}
command -v "$NM" >/dev/null 2>&1 || NM=nm
READELF=${READELF:-aarch64-unknown-linux-gnu-readelf}
command -v "$READELF" >/dev/null 2>&1 || READELF=readelf

echo "== file"
command -v file >/dev/null 2>&1 && file "$LIB"

echo
echo "== the three symbols the loader resolves"
fail=0
for s in CreateScriptI LoadScriptI RunScriptI; do
    if "$NM" -D --defined-only "$LIB" 2>/dev/null | grep -qE "[[:space:]]$s$"; then
        echo "   $s ok"
    else
        echo "   $s MISSING"
        fail=1
    fi
done

echo
echo "== required glibc versions (the camera has 2.25)"
vers=$("$READELF" -V "$LIB" 2>/dev/null | grep -oE 'GLIBC_2\.[0-9]+' | sort -u -V || true)
if [ -z "$vers" ]; then
    echo "   none listed (static or no versioned references)"
else
    for v in $vers; do
        minor=$(echo "$v" | sed 's/GLIBC_2\.//')
        if [ "$minor" -gt 25 ]; then
            echo "   $v  TOO NEW - the camera cannot resolve this"
            fail=1
        else
            echo "   $v  ok"
        fi
    done
fi

echo
echo "== dynamic dependencies"
"$READELF" -d "$LIB" 2>/dev/null | grep -E 'NEEDED|SONAME|INIT_ARRAY' || true

echo
if [ "$fail" -ne 0 ]; then
    echo "NOT ready for the camera - fix the above first."
    exit 1
fi
echo "looks loadable by the camera's glibc 2.25."
