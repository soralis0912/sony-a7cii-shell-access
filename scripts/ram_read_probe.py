#!/usr/bin/env python3
"""Try the service protocol's RAM_READ, read-only, and pin down its payload format.

libsencore.so carries one 0x48-byte command record per adjust command:
[u32 subsystem][u16 category][u8 command][u8 flags][name]. RAM_READ is command
0xfe and RAM_WRITE is 0xff, and they exist under several categories at once:

    category 0x0601  RAM_READ flags 0x00   RAM_WRITE flags 0x40   (the Senser
                                                                   block `bk r` uses)
    category 0x0421  RAM_READ flags 0x00   RAM_WRITE flags 0x00
    also 0x0404, 0x0405, 0x040f, 0x0415, 0x0418, 0x0d21 - all flags 0x00

0x0421 matters twice over: its flags are 0x00 on the write side too, and
SubsystemCommunicationCommand::TransactionStart translates PFUNC 0xff03
(MemoryDump) into subsystem command 0x421 - so PMCA's own readMemory, whose
header is {u32 base, u32 size}, is this command by another road. That header is
the first format this tries.

Only RAM_READ is sent. Nothing is written, and the target is the boot ROM at
0xffff0000, which PMCA's own `bootrom` command reads: known, read-only
territory. The response is dumped and the read is repeated once, because a
format that is being misparsed tends not to return the same bytes twice.

  cd ~/git/a7c2/Sony-PMCA-RE
  sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/ram_read_probe.py
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


def _bootstrap_pmca() -> str:
    import os
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
        roots.append(str(Path(here).resolve().parents[2] / "Sony-PMCA-RE"))
    for root in roots:
        path = Path(root).expanduser()
        tried.append(str(path))
        if (path / "pmca" / "__init__.py").is_file():
            sys.path.insert(0, str(path.resolve()))
            return str(path.resolve())
    sys.exit("Could not find the `pmca` package. Looked in:\n  %s" % "\n  ".join(tried))


PMCA_ROOT = _bootstrap_pmca()

RAM_READ = 0xFE          # never 0xff here: that is RAM_WRITE
CATEGORIES = [
    (0x0421, "PFUNC 0xff03 (MemoryDump) is translated to this one; write side is flags 0x00"),
    (0x0601, "the Senser block that bk r uses; its write side is flags 0x40"),
]


def forms(base: int, size: int):
    """Candidate payloads, cheapest first."""
    yield "base,size as u32", struct.pack("<II", base, size)
    yield "0x00 + base,size", b"\x00" + struct.pack("<II", base, size)
    yield "0x00,0x00,0x00 + base,size", b"\x00\x00\x00" + struct.pack("<II", base, size)


def dump(data: bytes, limit: int = 64) -> None:
    for off in range(0, min(len(data), limit), 16):
        row = data[off:off + 16]
        print("      %#06x  %-47s %s"
              % (off, row.hex(" "),
                 "".join(chr(c) if 32 <= c < 127 else "." for c in row)))
    if len(data) > limit:
        print("      ... %d bytes in total" % len(data))


def probe(camera, args) -> None:
    print("target %#010x, %d bytes (the boot ROM, as PMCA's own bootrom reads)"
          % (args.base, args.size))
    print("sending RAM_READ (0x%02x) only. RAM_WRITE is never sent by this script.\n"
          % RAM_READ)

    for category, why in CATEGORIES:
        print("category %#06x - %s" % (category, why))
        for label, payload in forms(args.base, args.size):
            try:
                first = camera._sendAdjustControlPacket(category, RAM_READ, payload)
            except Exception as exc:
                print("  %-26s refused (%s)" % (label, exc or type(exc).__name__))
                continue
            print("  %-26s %d bytes back" % (label, len(first)))
            dump(first)
            try:
                second = camera._sendAdjustControlPacket(category, RAM_READ, payload)
            except Exception as exc:
                print("      second read refused (%s)" % (exc or "?"))
                continue
            print("      repeat identical: %s" % (first == second))
            if first == second and len(first) >= args.size:
                print("\n  This format answers consistently. Record it; the next step")
                print("  (locating a known page, then a single-byte RAM_WRITE) is a")
                print("  separate decision, not something this script does.")
                return
        print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=lambda s: int(s, 0), default=0xFFFF0000)
    ap.add_argument("--size", type=lambda s: int(s, 0), default=0x40)
    args = ap.parse_args()
    if args.size > 0x1000:
        ap.error("keep the first reads small; %#x is too much" % args.size)

    from pmca.commands.usb import senserShellCommand
    print("using pmca from %s" % PMCA_ROOT, flush=True)

    done = False

    def go(camera):
        nonlocal done
        probe(camera, args)
        done = True

    senserShellCommand(complete=go)
    if not done:
        print("Camera never reached service mode; reconnect and run again.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
