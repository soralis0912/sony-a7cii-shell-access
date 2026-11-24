#!/usr/bin/env python3
"""Read the custom-LUT backup slots off an ILCE-7CM2 in service mode.

Reads only. Nothing is written to the backup and no file is sent.

There are 50 slots, each described by five backup properties. Their ids are
**not** consecutive: only slots 0..15 of each family sit in one run, and the
rest are scattered over further blocks. The address table below is generated
from the feature-research repository's BKID inventory for firmware 2.01, where
every id is read out of the firmware's own name records rather than guessed.

Taking the ids as base + n, which an earlier version of this script did, reads
the wrong property past slot 15 - IS_EXIST_USER_LUT16 is 0x02cf141e, not
0x02cf106c, and 0x02cf106c is USER_LUT_FILE_ID0. That is what produced a bogus
report of slots 16..49 all differing from their defaults: real properties, read
under the wrong names.

Run it from inside a Sony-PMCA-RE checkout:

    cd ~/git/a7c2/Sony-PMCA-RE
    sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/read_user_lut_slots.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey_readonly import PMCA_ROOT  # noqa: E402  (runs the pmca bootstrap)

import argparse  # noqa: E402

FAMILIES = [
    ("IS_EXIST",           "00", [
        ( 0, 15, 0x02CF105C),
        (16, 49, 0x02CF141E),
    ]),
    ("FILE_ID",            "00" * 64, [
        ( 0, 15, 0x02CF106C),
        (16, 31, 0x02CF1440),
        (32, 43, 0x02CF1461),
        (44, 44, 0x02CF1668),
        (45, 45, 0x02CF166C),
        (46, 46, 0x02CF16AB),
        (47, 47, 0x02CF16B4),
        (48, 49, 0x02CF16D6),
    ]),
    ("ATTR_INPUT_GAMUT",   "01", [
        ( 0, 15, 0x02CF107C),
        (16, 49, 0x02CF16D8),
    ]),
    ("ATTR_OUTPUT_PROCAM", "00", [
        ( 0, 15, 0x02CF1450),
        (16, 49, 0x02CF176A),
    ]),
    ("ATTR_AE_LEVEL_OFF",  "00", [
        ( 0, 15, 0x02CF104C),
        (16, 17, 0x02CF13A8),
        (18, 18, 0x02CF13AE),
        (19, 21, 0x02CF13B4),
        (22, 35, 0x02CF13C6),
        (36, 49, 0x02CF1410),
    ]),
]
SLOTS = 50


def address(runs, slot: int) -> int:
    """The property id for this slot, from the generated run table."""
    for lo, hi, base in runs:
        if lo <= slot <= hi:
            return base + (slot - lo)
    raise KeyError("slot %d is not in the table" % slot)


def absent(data) -> bool:
    """True when the camera gave us no value for a property.

    Reading a slot this model does not provision comes back empty rather than
    as an error, and an empty answer must not be mistaken for a changed one -
    the first version of this script counted slots 16..49 as "changed" for
    exactly that reason.
    """
    return data is None or (isinstance(data, (bytes, bytearray)) and len(data) == 0)


def hexs(data) -> str:
    if data is None:
        return "(no value)"
    if isinstance(data, (bytes, bytearray)):
        return bytes(data).hex()
    return str(data)


def printable(data) -> str:
    """Show a FILE_ID as text when it looks like a name."""
    if not isinstance(data, (bytes, bytearray)):
        return ""
    s = bytes(data).split(b"\0", 1)[0]
    if s and all(32 <= c < 127 for c in s):
        return '  "%s"' % s.decode("ascii")
    return ""


def read_slots(camera, slots: int, show_all: bool) -> None:
    print("slots read: 0..%d" % (slots - 1))
    interesting = []
    missing = []
    values = {}
    for name, default, runs in FAMILIES:
        for n in range(slots):
            try:
                raw = camera.readBackup(address(runs, n))
            except Exception as exc:                      # noqa: BLE001
                raw = None
                err = str(exc)
            else:
                err = None
            values[(name, n)] = (raw, err)
            if err is None and not absent(raw) and hexs(raw) != default \
                    and n not in interesting:
                interesting.append(n)
            if (err is not None or absent(raw)) and n not in missing:
                missing.append(n)

    if interesting:
        print("\nslots that differ from the firmware default: %s"
              % ", ".join(str(n) for n in sorted(interesting)))
    else:
        print("\nevery slot still holds the firmware default - nothing registered")
    if missing:
        print("slots the camera returned nothing for, i.e. not provisioned on "
              "this model: %s" % ", ".join(str(n) for n in sorted(missing)))

    to_show = sorted(set(interesting) | ({0, 1, 2, 3} if not show_all else set(range(slots))))
    for n in to_show:
        print("\nslot %d" % n)
        for name, default, runs in FAMILIES:
            pid = address(runs, n)
            raw, err = values[(name, n)]
            if err is not None:
                print("  %-19s 0x%08x  read failed: %s" % (name, pid, err))
                continue
            if absent(raw):
                print("  %-19s 0x%08x  (no value)" % (name, pid))
                continue
            h = hexs(raw)
            mark = "" if h == default else "   <-- changed"
            shown = h if len(h) <= 72 else h[:72] + "..."
            print("  %-19s 0x%08x  %s%s%s"
                  % (name, pid, shown, printable(raw), mark))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slots", type=int, default=SLOTS,
                    help="how many slots to read (default and maximum %d)" % SLOTS)
    ap.add_argument("--all", action="store_true",
                    help="print every slot, not just the changed ones")
    args = ap.parse_args()
    if not 1 <= args.slots <= SLOTS:
        print("there are %d slots" % SLOTS, file=sys.stderr)
        return 2

    from pmca.commands.usb import senserShellCommand
    print("using pmca from %s" % PMCA_ROOT, flush=True)

    done = False

    def collect(camera):
        nonlocal done
        read_slots(camera, args.slots, args.all)
        done = True

    senserShellCommand(complete=collect)
    if not done:
        print("Camera never reached service mode; reconnect and run again.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
