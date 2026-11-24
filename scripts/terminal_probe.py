#!/usr/bin/env python3
"""Print the service interface's USB endpoints. Reads descriptors, sends nothing.

PMCA's `shell` talks on `ep=1`, which is not an endpoint address:
`GenericUsbDriver.read/write` take an *index* into the lists of bulk IN and
bulk OUT endpoints found on the interface. If this camera is laid out
differently from the one that assumption came from, the write goes to the
wrong endpoint, nothing typed reaches the camera, and the shell reports an
empty `Error:`. The endpoint list alone shows whether that is what happened.

**This version performs no USB transfers on the endpoints.** An earlier version
wrote a newline to every (OUT, IN) pair in turn to see which answered, and
that wedged the host's USB stack hard enough to freeze the machine: writing to
a bulk endpoint the kernel owns is not a safe thing to try blindly. Decide from
the descriptors first; if a transfer test is ever needed, it belongs on one
named pair, with the camera's own documentation to justify it, not on a sweep.

  cd ~/git/a7c2/Sony-PMCA-RE
  sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/terminal_probe.py
"""
from __future__ import annotations

import argparse
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

TYPE = {0: "control", 1: "isochronous", 2: "bulk", 3: "interrupt"}


def report(camera) -> None:
    driver = camera.dev.driver

    print("endpoint descriptors on the service interface:")
    try:
        for ep in driver.backend.getEndpoints():
            addr = ep.bEndpointAddress
            print("  %#04x  %-11s %-3s  max packet %s"
                  % (addr, TYPE.get(ep.bmAttributes & 3, "?"),
                     "IN" if addr & 0x80 else "OUT",
                     getattr(ep, "wMaxPacketSize", "?")))
    except Exception as exc:
        print("  could not list them: %s: %s" % (type(exc).__name__, exc))

    print("\nwhat PMCA's indices resolve to:")
    for name, eps in (("bulk IN ", driver.epIn), ("bulk OUT", driver.epOut)):
        print("  %s %s" % (name, ", ".join("[%d]=%#04x" % (i, e)
                                           for i, e in enumerate(eps))))
    print("\n  `shell` uses index 1 of each:")
    for name, eps in (("IN ", driver.epIn), ("OUT", driver.epOut)):
        if len(eps) > 1:
            print("    %s %#04x" % (name, eps[1]))
        else:
            print("    %s MISSING - only %d bulk endpoint(s) in this direction,"
                  " so `shell` cannot work as written" % (name, len(eps)))

    print("\nFor comparison, the published A7 IV figures are IN 0x83, OUT 0x04.")
    print("Nothing was sent to any endpoint.")


def main() -> int:
    argparse.ArgumentParser(
        description="List the service interface's USB endpoints. Sends nothing."
    ).parse_args()

    from pmca.commands.usb import senserShellCommand
    print("using pmca from %s" % PMCA_ROOT, flush=True)

    done = False

    def run(camera):
        nonlocal done
        report(camera)
        done = True

    senserShellCommand(complete=run)
    if not done:
        print("Camera never reached service mode; reconnect and run again.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
