#!/usr/bin/env python3
"""Find out which USB endpoints the service terminal actually uses.

PMCA's `shell` enables the terminal and then talks on `ep=1`, which is not an
endpoint address: `GenericUsbDriver.read/write` take an *index* into the lists
of bulk IN and bulk OUT endpoints it found on the interface. If this camera's
service interface is laid out differently from the one that assumption came
from, the write fails and the shell reports an empty `Error:` while nothing
typed ever reaches the camera.

So: print the endpoints, turn the terminal on, and for every plausible
(IN, OUT) index pair send one newline and listen briefly. A pair that answers
is the pair a shell session needs.

What this sends to the camera: the terminal-enable command, one newline per
pair tried, and the terminal-disable command at the end. Nothing is written to
the backup or to any file.

  cd ~/git/a7c2/Sony-PMCA-RE
  sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/terminal_probe.py
"""
from __future__ import annotations

import argparse
import sys
import time
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

LISTEN = 0.6          # seconds to wait for an answer after the newline
CHUNK = 0x40


def describe(driver) -> None:
    print("bulk IN  endpoints: %s" % ", ".join("%#04x" % e for e in driver.epIn))
    print("bulk OUT endpoints: %s" % ", ".join("%#04x" % e for e in driver.epOut))
    print("PMCA's `shell` uses index 1 of each, i.e. %s / %s"
          % ("%#04x" % driver.epIn[1] if len(driver.epIn) > 1 else "MISSING",
             "%#04x" % driver.epOut[1] if len(driver.epOut) > 1 else "MISSING"))
    try:
        print("\nendpoint descriptors:")
        for ep in driver.backend.getEndpoints():
            print("  address %#04x  attributes %#04x  max packet %s"
                  % (ep.bEndpointAddress, ep.bmAttributes,
                     getattr(ep, "wMaxPacketSize", "?")))
    except Exception as exc:
        print("  (could not list descriptors: %s)" % exc)


def try_pair(driver, out_i: int, in_i: int, probe: bytes) -> bytes:
    driver.write(probe, ep=out_i)
    got = b""
    deadline = time.time() + LISTEN
    while time.time() < deadline:
        try:
            chunk = driver.read(CHUNK, ep=in_i, timeout=100)
        except Exception:
            chunk = b""
        if chunk:
            got += chunk
            deadline = time.time() + 0.2
    return got


def probe(camera, args) -> None:
    driver = camera.dev.driver
    describe(driver)

    print("\nenabling the terminal...")
    camera.setTerminalEnable(True)
    try:
        for out_i in range(len(driver.epOut)):
            for in_i in range(len(driver.epIn)):
                label = "out %#04x -> in %#04x" % (driver.epOut[out_i],
                                                   driver.epIn[in_i])
                try:
                    got = try_pair(driver, out_i, in_i, args.probe.encode())
                except Exception as exc:
                    print("  %-28s write failed (%s: %s)"
                          % (label, type(exc).__name__, exc or "no message"))
                    continue
                if got:
                    print("  %-28s %d bytes: %r" % (label, len(got), got[:160]))
                else:
                    print("  %-28s silent" % label)
    finally:
        print("\ndisabling the terminal...")
        camera.setTerminalEnable(False)
    print("\nA pair that answered is the one a shell needs. If every pair is")
    print("silent but none failed, the terminal exists and carries no shell:")
    print("the interactive subsystem is not bound (ulogio's ISYS is 0 in this")
    print("camera's /setting/ulogio.bin), which is a different problem from")
    print("talking on the wrong endpoint.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", default="\n",
                    help="what to send on each pair (default: one newline)")
    args = ap.parse_args()

    from pmca.commands.usb import senserShellCommand
    print("using pmca from %s" % PMCA_ROOT, flush=True)

    done = False

    def run(camera):
        nonlocal done
        probe(camera, args)
        done = True

    senserShellCommand(complete=run)
    if not done:
        print("Camera never reached service mode; reconnect and run again.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
