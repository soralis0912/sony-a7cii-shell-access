#!/bin/sh
# Check a built libJit.so against what the camera can load.
#
# The camera's root filesystem is glibc 2.25 and Sony's own libraries there
# reference GLIBC_2.17, so a library built against a newer glibc can ask for
# symbol versions that do not exist on the camera. A library with no DT_NEEDED
# at all sidesteps that entirely.
set -e
cd "$(dirname "$0")"
PATH="/opt/homebrew/bin:$PATH"
export PATH
LIB=${1:-libJit.so}

pick() {
    for c in "$@"; do command -v "$c" >/dev/null 2>&1 && { echo "$c"; return; }; done
    echo ""
}
NM=$(pick aarch64-unknown-linux-gnu-nm aarch64-elf-nm nm)
READELF=$(pick aarch64-unknown-linux-gnu-readelf aarch64-elf-readelf readelf)
[ -n "$READELF" ] || { echo "no readelf available" >&2; exit 1; }

fail=0

echo "== type"
"$READELF" -h "$LIB" | grep -E 'Class:|Data:|Type:|Machine:'
"$READELF" -h "$LIB" | grep -q 'DYN (Shared object file)' || { echo "   not a shared object"; fail=1; }
"$READELF" -h "$LIB" | grep -q 'AArch64' || { echo "   not AArch64"; fail=1; }

echo
echo "== the three symbols jit_thread resolves"
for s in CreateScriptI LoadScriptI RunScriptI; do
    if "$NM" -D --defined-only "$LIB" 2>/dev/null | grep -qE "[[:space:]]$s$"; then
        echo "   $s ok"
    else
        echo "   $s MISSING"
        fail=1
    fi
done

echo
echo "== constructor"
if "$READELF" -d "$LIB" | grep -q INIT_ARRAY; then
    echo "   INIT_ARRAY present, so dlopen runs it"
else
    echo "   no INIT_ARRAY - nothing would run on load"
    fail=1
fi

echo
echo "== what it needs from the camera"
needed=$("$READELF" -d "$LIB" | grep NEEDED || true)
if [ -z "$needed" ]; then
    echo "   nothing (no DT_NEEDED) - glibc version cannot be an issue"
else
    echo "$needed"
    vers=$("$READELF" -V "$LIB" 2>/dev/null | grep -oE 'GLIBC_2\.[0-9]+' | sort -u -V || true)
    for v in $vers; do
        minor=$(echo "$v" | sed 's/GLIBC_2\.//')
        if [ "$minor" -gt 25 ]; then
            echo "   $v  TOO NEW - the camera has 2.25 and cannot resolve it"
            fail=1
        else
            echo "   $v  ok"
        fi
    done
fi

echo
echo "== undefined symbols"
undef=$("$NM" -D --undefined-only "$LIB" 2>/dev/null || true)
[ -z "$undef" ] && echo "   none" || echo "$undef"

echo
[ "$fail" -eq 0 ] || { echo "NOT ready for the camera - fix the above."; exit 1; }
echo "structurally ready. Loading on the camera is still unverified."
