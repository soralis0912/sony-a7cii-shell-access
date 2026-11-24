#!/usr/bin/env python3
"""Send a built libJit.so to the camera and read back the marker it writes.

This is the one script here that WRITES to the camera. It sends exactly one
Jiritsu command that writes - SET_FILE (category 0x1001, command 0x4007) with
file number 2, which is /tmp/jiritsu/libJit.so - and then reads two files back
with the read-only pair SET_FILE_PATH (0x400f) + GET_FILE2 (0x4011).

What happens on the camera, from libJiritsu.so 2.01:

  SET_FILE writes the bytes to /tmp/jiritsu/libJit.so, on /dev/nflasha6 which
  the handler mounts as vfat each time. jit_thread then mounts a 5 MB ramdisk,
  copies the file onto it, dlopens that copy, and resolves CreateScriptI,
  LoadScriptI and RunScriptI. The library's constructor runs at dlopen.

Nothing in /etc, /setting or the backup is touched, and the loaded image lives
on a ramdisk. The file written to /tmp/jiritsu does persist until something
clears it.

  cd ~/git/a7c2/Sony-PMCA-RE
  sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/jit_load.py \
      ~/git/a7c2/sony-a7cii-shell-access/native/jit/libJit.so

It refuses to send a file that is not an AArch64 ET_DYN shared object
exporting the three symbols, and it asks before sending.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import struct
import sys


def _bootstrap_pmca() -> str:
    """Make the `pmca` package importable; see survey_readonly.py."""
    tried, roots = [], []
    argv = sys.argv[1:]
    if "--pmca-root" in argv:
        i = argv.index("--pmca-root")
        if i + 1 < len(argv):
            roots.append(argv[i + 1])
            del argv[i:i + 2]
            sys.argv[1:] = argv
    if os.environ.get("PMCA_ROOT"):
        roots.append(os.environ["PMCA_ROOT"])
    roots.append(os.getcwd())
    here = globals().get("__file__")
    if here:
        roots.append(str(pathlib.Path(here).resolve().parents[2] / "Sony-PMCA-RE"))
    for root in roots:
        path = pathlib.Path(root).expanduser()
        tried.append(str(path))
        if (path / "pmca" / "__init__.py").is_file():
            sys.path.insert(0, str(path.resolve()))
            return str(path.resolve())
    sys.exit("Could not find the `pmca` package. Looked in:\n  %s\n"
             "Pass --pmca-root /path/to/Sony-PMCA-RE." % "\n  ".join(tried))


PMCA_ROOT = _bootstrap_pmca()

CATEGORY = 0x1001
SET_FILE = 0x4007          # the only write command this script will send
SET_FILE_PATH = 0x400F
GET_FILE2 = 0x4011
GET_FILELIST = 0x400A      # read-only: what is already on the partition

FILE_LIBJIT = 2            # /tmp/jiritsu/libJit.so
MODE_RAW = 0               # write the bytes as given

MARKER = "/tmp/jiritsu/jit_hello.txt"
JITLOG = "/tmp/jiritsu/jit.log"
LIMIT = 25 * 1024 * 1024   # the handler refuses once /tmp/jiritsu/* passes this

ERRORS = {8: "open failed", 9: "write failed", 15: "over the 25 MiB limit",
          17: "/tmp/jbusy exists - the service is mid-operation",
          21: "dmm allocation failed", 513: "bad parameter"}
JIT_ERRORS = {11: "ramdisk mount failed", 16: "CreateScriptI returned 0",
              18: "dlopen failed", 19: "LoadScriptI missing",
              20: "CreateScriptI missing", 21: "copy to the ramdisk failed"}


def vet(path: pathlib.Path) -> bytes:
    """Refuse anything that is not the kind of library the loader expects."""
    blob = path.read_bytes()
    if blob[:4] != b"\x7fELF" or blob[4] != 2 or blob[5] != 1:
        raise SystemExit("%s is not a little-endian ELF64 file" % path)
    e_type, e_machine = struct.unpack_from("<HH", blob, 16)
    if e_type != 3:
        raise SystemExit("%s is not ET_DYN (a shared object)" % path)
    if e_machine != 183:
        raise SystemExit("%s is not AArch64" % path)
    for sym in (b"CreateScriptI", b"LoadScriptI", b"RunScriptI"):
        if sym not in blob:
            raise SystemExit("%s does not export %s" % (path, sym.decode()))
    if len(blob) > LIMIT:
        raise SystemExit("%s is larger than the 25 MiB the handler allows" % path)
    return blob


def jiritsu_read(camera, path: str):
    target = b"../.." + path.encode("latin1")
    try:
        camera._sendAdjustControlPacket(CATEGORY, SET_FILE_PATH, b"\x00" + target)
        response = camera._sendAdjustControlPacket(CATEGORY, GET_FILE2, b"\x00\xff\x00")
    except Exception as exc:
        return None, exc
    if len(response) < 4:
        return None, RuntimeError("short response")
    status = int.from_bytes(response[:4], "little")
    if status:
        return None, RuntimeError("inner status 0x%08x" % status)
    return response[4:], None


def list_area(camera):
    """Read-only: ask what is already under /tmp/jiritsu before writing there."""
    for payload in (b"\x00", b"\x00\xff\x00", b""):
        try:
            response = camera._sendAdjustControlPacket(CATEGORY, GET_FILELIST, payload)
        except Exception as exc:
            print("   GET_FILELIST(%s) refused: %s" % (payload.hex() or "empty", exc))
            continue
        print("   GET_FILELIST(%s) returned %d byte(s)"
              % (payload.hex() or "empty", len(response)))
        if response:
            text = "".join(chr(c) if 32 <= c < 127 else "." for c in response[:800])
            print("   | %s" % text)
        return response
    return None


def run(camera, blob: bytes, out_dir: pathlib.Path, assume_yes: bool) -> None:
    camera.readHasp()
    print("what is on the partition now (read-only):")
    list_area(camera)
    print()
    print("about to write %d bytes to /tmp/jiritsu/libJit.so (file number %d)"
          % (len(blob), FILE_LIBJIT))
    print("that path is what get_jiritsu_area_filename(2) returns; the switch in")
    print("libJiritsu.so 2.01 maps 0..4 to tmmc.jit, DIAC.csv, libJit.so, jit.log")
    print("and history.txt, and the handler refuses jit.log and history.txt.")
    print("sha256 %s" % hashlib.sha256(blob).hexdigest())
    print("the service will then dlopen a ramdisk copy and run its constructor.")
    if not assume_yes:
        if input("type yes to send: ").strip().lower() != "yes":
            print("nothing sent.")
            return

    payload = bytes([0x00, FILE_LIBJIT, MODE_RAW]) + blob
    try:
        response = camera._sendAdjustControlPacket(CATEGORY, SET_FILE, payload)
    except Exception as exc:
        print("SET_FILE refused: %s" % exc)
        print("(error codes: %s)" % ", ".join("%d=%s" % kv for kv in ERRORS.items()))
        return
    print("SET_FILE returned %d byte(s)%s"
          % (len(response), ": " + response.hex() if response else ""))
    if len(response) >= 4:
        status = int.from_bytes(response[:4], "little")
        if status:
            print("  inner status %d: %s" % (status, ERRORS.get(status, "unknown")))

    for path, label in ((MARKER, "the marker our constructor writes"),
                        (JITLOG, "the loader's own log")):
        data, exc = jiritsu_read(camera, path)
        print("\n%s (%s):" % (path, label))
        if exc is not None:
            print("   not readable (%s)" % exc)
            continue
        local = out_dir / path.strip("/").replace("/", "_")
        local.write_bytes(data)
        print("   %d bytes, saved to %s" % (len(data), local))
        text = data.decode("latin1")
        for line in text.splitlines()[:40]:
            print("   | %s" % line)
        if path == MARKER and "libJit loaded" in text:
            print("\n   the library was loaded and our code ran inside the service.")
        if path == JITLOG:
            for code, meaning in JIT_ERRORS.items():
                if ("err %d" % code) in text or ("=%d" % code) in text:
                    print("   possible loader error %d: %s" % (code, meaning))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("library", type=pathlib.Path, help="the built libJit.so")
    ap.add_argument("--dir", type=pathlib.Path, default=pathlib.Path("."))
    ap.add_argument("--yes", action="store_true", help="skip the confirmation")
    ap.add_argument("--list-only", action="store_true",
                    help="only list what is under /tmp/jiritsu and exit; writes nothing")
    args = ap.parse_args()

    if not args.library.is_file():
        print("no such file: %s" % args.library, file=sys.stderr)
        return 2
    blob = vet(args.library)
    args.dir.mkdir(parents=True, exist_ok=True)

    from pmca.commands.usb import senserShellCommand
    print("using pmca from %s" % PMCA_ROOT)

    done = False

    def collect(camera):
        nonlocal done
        if args.list_only:
            camera.readHasp()
            print("read-only listing of /tmp/jiritsu (nothing is written):")
            list_area(camera)
        else:
            run(camera, blob, args.dir, args.yes)
        done = True

    senserShellCommand(complete=collect)
    if not done:
        print("Camera never reached service mode; reconnect and run again.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
