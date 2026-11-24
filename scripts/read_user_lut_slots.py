#!/usr/bin/env python3
"""Read the custom-LUT backup slots off an ILCE-7CM2 in service mode.

Reads only. Nothing is written to the backup and no file is sent.

The camera keeps 50 user-LUT slots, each described by five backup properties.
The addresses come from the feature-research repository's BKID inventory for
firmware 2.01, where each family is 50 consecutive ids:

    IS_EXIST_USER_LUT<n>              0x02cf105c + n   default 0x00 (EMPTY)
    USER_LUT_FILE_ID<n>               0x02cf106c + n   default 64 zero bytes
    USER_LUT_ATTR_INPUT_GAMUT<n>      0x02cf107c + n   default 0x01
    USER_LUT_ATTR_OUTPUT_PROCAM<n>    0x02cf1450 + n   default 0x00
    USER_LUT_ATTR_AE_LEVEL_OFFSET<n>  0x02cf104c + n   default 0x00

Point of the exercise: import a LUT through the camera's own menu, from
PRIVATE/SONY/PRO/LUT on the card, then run this. Whatever differs from the
defaults is the registration the import performed - which is what a slot would
have to be given to make a LUT dropped straight into /usr/data/lut appear.

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
    ("IS_EXIST",          0x02CF105C, "00"),
    ("FILE_ID",           0x02CF106C, "00" * 64),
    ("ATTR_INPUT_GAMUT",  0x02CF107C, "01"),
    ("ATTR_OUTPUT_PROCAM", 0x02CF1450, "00"),
    ("ATTR_AE_LEVEL_OFF", 0x02CF104C, "00"),
]
SLOTS = 50


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
    values = {}
    for name, base, default in FAMILIES:
        for n in range(slots):
            try:
                raw = camera.readBackup(base + n)
            except Exception as exc:                      # noqa: BLE001
                raw = None
                err = str(exc)
            else:
                err = None
            values[(name, n)] = (raw, err)
            if err is None and hexs(raw) != default and n not in interesting:
                interesting.append(n)

    if interesting:
        print("\nslots that differ from the firmware default: %s"
              % ", ".join(str(n) for n in sorted(interesting)))
    else:
        print("\nevery slot still holds the firmware default - nothing registered")

    to_show = sorted(set(interesting) | ({0, 1, 2, 3} if not show_all else set(range(slots))))
    for n in to_show:
        print("\nslot %d" % n)
        for name, base, default in FAMILIES:
            raw, err = values[(name, n)]
            if err is not None:
                print("  %-19s 0x%08x  read failed: %s" % (name, base + n, err))
                continue
            h = hexs(raw)
            mark = "" if h == default else "   <-- changed"
            shown = h if len(h) <= 72 else h[:72] + "..."
            print("  %-19s 0x%08x  %s%s%s"
                  % (name, base + n, shown, printable(raw), mark))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slots", type=int, default=SLOTS,
                    help="how many slots to read (default %d)" % SLOTS)
    ap.add_argument("--all", action="store_true",
                    help="print every slot, not just the changed ones")
    args = ap.parse_args()

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
