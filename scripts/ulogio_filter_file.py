#!/usr/bin/env python3
"""Build or read the ulogio filter-setting file (/setting/ulogio.bin).

The ulogio kernel module takes that path as a module parameter. The p3 initrd
loads it with

    insmod /usr/kmod/osal_ulogio.ko ulogio_initfile=/setting/ulogio.bin \
        ulogio_cp_filterfile=/cp/filter.bin

and `ulogio_filter_load_setting` parses the file as a flat stream of records:

    u32 length     bytes from the start of this record to the start of the next
    u32 tag        four ASCII characters, little-endian in the file
    u32 value      the setting (fixed-size records are length 12)

The telnet listener's enable flag is the `TELN` record; the CLI's
`ulogio telnet up` is the same flag, and the camera has to reboot for the
listener to come up. Everything here is derived from ILCE-7CM2 2.01's
`libosal_ulogio.so` (`ulogio_filter_load_setting` at VA 0x6010 and
`ulogio_filter_save_setting` at VA 0x6364); the kernel module carries the same
parser.

  python3 scripts/ulogio_filter_file.py --telnet 1 -o /tmp/ulogio.bin
  (--telnet is the TELN record; the other tags take --dbgl, --term and so on)
  python3 scripts/ulogio_filter_file.py --parse /tmp/ulogio.bin

Writing the file to a camera is a persistent change to /setting (nflasha2, vfat,
read-write). It is undone by restoring the previous file, or by deleting it.
This script only makes and reads bytes on the PC.
"""
from __future__ import annotations

import argparse
import pathlib
import struct
import sys

# tag -> what the loader does with the value, in the order save_setting writes
FIXED_TAGS = ["DBGL", "FLTA", "TERM", "EFRE", "TTAG", "TELN", "PROX"]
MEANING = {
    "DBGL": "debug level",
    "FLTA": "abort flag",
    "TERM": "terminal output",
    "EFRE": "efree flag",
    "TTAG": "time-tag type",
    "TELN": "telnet listener enable (what `ulogio telnet up` sets)",
    "PROX": "proxy (u32)",
    "SFLT": "subsystem filters: u32 count, then one u32 per filter",
    "CFLT": "component filters: u32 count, then one u64 per filter",
    "FVER": "format version; the loader rejects anything but 0x10",
}
RECORD = 12


def record(tag: str, value: int) -> bytes:
    if len(tag) != 4:
        raise ValueError("a tag is four characters: %r" % tag)
    return struct.pack("<I4sI", RECORD, tag.encode("ascii"), value)


def build(values: dict[str, int], version: bool) -> bytes:
    out = b""
    if version:
        out += record("FVER", 0x10)
    for tag in FIXED_TAGS:
        if tag in values:
            out += record(tag, values[tag])
    return out


def parse(blob: bytes) -> int:
    pos = 0
    n = 0
    while pos + 8 <= len(blob):
        length, tag = struct.unpack_from("<I4s", blob, pos)
        name = tag.decode("latin1")
        if length < 8 or pos + length > len(blob):
            print("%#06x  BROKEN  length %d from %#x does not fit in %d bytes"
                  % (pos, length, pos, len(blob)))
            return 1
        payload = blob[pos + 8:pos + length]
        shown = struct.unpack("<I", payload)[0] if len(payload) == 4 else payload.hex()
        print("%#06x  %-4s  len %-4d  %-10s %s"
              % (pos, name, length, shown, MEANING.get(name, "unknown tag")))
        if name == "FVER" and shown != 0x10:
            print("        the loader refuses this: version must be 0x10")
        pos += length
        n += 1
    if pos != len(blob):
        print("%#06x  %d trailing byte(s) the loader will ignore"
              % (pos, len(blob) - pos))
    print("\n%d record(s)" % n)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parse", type=pathlib.Path, help="read a file and print it")
    ap.add_argument("-o", "--out", type=pathlib.Path, help="write the built file here")
    ap.add_argument("--version-record", action="store_true",
                    help="also emit FVER 0x10 (the camera's own saver does not)")
    ap.add_argument("--telnet", dest="teln", type=lambda s: int(s, 0),
                    help=MEANING["TELN"])
    for tag in FIXED_TAGS:
        if tag == "TELN":
            continue
        ap.add_argument("--" + tag.lower(), type=lambda s: int(s, 0),
                        help=MEANING[tag])
    args = ap.parse_args()

    if args.parse:
        if not args.parse.is_file():
            print("no such file: %s" % args.parse, file=sys.stderr)
            return 2
        return parse(args.parse.read_bytes())

    values = {t: getattr(args, t.lower()) for t in FIXED_TAGS
              if getattr(args, t.lower()) is not None}
    if not values:
        ap.error("give at least one setting, or --parse a file")
    blob = build(values, args.version_record)
    if args.out:
        args.out.write_bytes(blob)
        print("wrote %s (%d bytes)" % (args.out, len(blob)))
    else:
        print(blob.hex(" "))
    parse(blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
