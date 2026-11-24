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


def _bootstrap_pmca() -> str:
    """Make the `pmca` package importable and say where it was found.

    Python puts this script's own directory on sys.path, not the directory you
    ran it from, so `cd`-ing into a Sony-PMCA-RE checkout is not enough on its
    own. Look, in order, at --pmca-root, $PMCA_ROOT, the current directory, and
    a Sony-PMCA-RE checkout sitting next to this repository. sudo strips
    PYTHONPATH, which is why the current directory matters.
    """
    import os
    import sys
    from pathlib import Path

    tried = []
    roots = []

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

    sys.exit("Could not find the `pmca` package. Looked in:\n  %s\n"
             "Pass --pmca-root /path/to/Sony-PMCA-RE, or run this from that "
             "checkout." % "\n  ".join(tried))


PMCA_ROOT = _bootstrap_pmca()

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
    from pmca.commands.usb import senserShellCommand
    print("using pmca from %s" % PMCA_ROOT, flush=True)

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
