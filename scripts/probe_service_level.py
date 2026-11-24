#!/usr/bin/env python3
"""Report which Sony service (Senser) privilege level the camera grants.

ILCE-7CM2 2.01 dispatches USB service packets through one of three tables in
libsencore.so, chosen by the level that authentication produced:

  adjCodeLevel 3 -> pFunc_level_A : 0x10 ProductInfo, 0x20 FirmwareUpdate,
                                    0x30 MiconAccess, 0x40 AdjustControl,
                                    0xff00 TestMode, 0xff02 Sonar
  adjCodeLevel 2 -> pFunc_level_B : 0x40, 0x10, 0x20
  adjCodeLevel 1 -> pFunc_level_C : 0x40 only
  adjCodeLevel 0 -> no table

The same code sets ``terminal_change_function_is_disabled = (adjCodeLevel != 3)``,
and ProductInfoFunc refuses the terminal-change command (0x00f1) while that byte
is set. So the service USB terminal is reachable exactly at level A.

This probe only reads. The one state-touching call is TERM_CHANGE with the
value 0, i.e. "turn the terminal off", which is what the camera already thinks;
it is sent because it is the cheapest way to learn whether the gate is open.
Nothing is written to the backup or to any file on the camera.

Run it from inside a Sony-PMCA-RE checkout (it imports ``pmca``):

  cd ~/git/a7c2/Sony-PMCA-RE
  sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/probe_service_level.py
"""
from __future__ import annotations

import sys

PROBE_BACKUP_ID = 0x02CF1700  # BKID_APP_SETTING_MODE_SHUTTER, read only


def probe(camera) -> None:
    results: dict[str, object] = {}

    def attempt(name, fn):
        try:
            fn()
        except Exception as exc:  # the camera answers errors as exceptions
            results[name] = exc
            print("  %-26s refused (%s)" % (name, exc))
            return False
        results[name] = True
        print("  %-26s ok" % name)
        return True

    print("Probing dispatch tables:")
    adjust = attempt("0x40 AdjustControl", lambda: camera.readBackup(PROBE_BACKUP_ID))
    product = attempt("0x10 ProductInfo", camera.readHasp)
    print("Probing the terminal gate (ProductInfo 0x00f1, value 0):")
    terminal = attempt("terminal change", lambda: camera._sendProductInfoPacket(
        *camera.SONY_PRODUCT_INFO_TERM_CHANGE, bytes([0])))

    print()
    if terminal:
        level, code = "A", 3
    elif product:
        level, code = "B", 2
    elif adjust:
        level, code = "C", 1
    else:
        level, code = "none", 0

    print("Service level: %s (adjCodeLevel %d)" % (level, code))
    if level == "A":
        print("The terminal gate is open: `shell` in the PMCA service shell should")
        print("attach the camera console over USB bulk, with nothing written to the")
        print("camera. Try it next.")
    elif level in ("B", "C"):
        print("The terminal gate is closed, and TestMode (0xff00, the Jiritsu front")
        print("end) is only in level A's table, so neither the USB terminal nor")
        print("Jiritsu file access is reachable with this authentication.")
        print("Backup properties (0x40 AdjustControl) remain available.")
    else:
        print("No table answered. Check that authentication actually completed.")


def main() -> int:
    try:
        from pmca.commands.usb import senserShellCommand
    except ImportError:
        print("Run this from a Sony-PMCA-RE checkout so that `pmca` is importable.",
              file=sys.stderr)
        return 2

    done = False

    def collect(camera):
        nonlocal done
        probe(camera)
        done = True

    senserShellCommand(complete=collect)
    if not done:
        print("Camera never reached service mode; reconnect and run again.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
