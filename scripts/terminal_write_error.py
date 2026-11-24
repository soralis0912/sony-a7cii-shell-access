#!/usr/bin/env python3
"""Show the libusb error that PMCA's `shell` hides when the terminal write fails.

PMCA's libusb backend turns every `usb.core.USBError` into a bare
`GenericUsbException()` with no arguments, so `print('Error: %s' % e)` shows
`Error:` and nothing else. `readTerminal` swallows that exception and returns
b""; `writeTerminal` does not, so the write is the half that ends the session.
Knowing *which* USB error it is decides what to do next: a stall from the
camera means the terminal is not accepting input, while a host-side refusal
means the problem is on this Mac.

This does exactly what `shell` does and no more: enable the terminal, send one
newline on the OUT endpoint `shell` uses, read on the IN endpoint it uses, then
disable the terminal. The endpoints come from the descriptors (IN 0x83, OUT
0x04 on this camera, which also match the published A7 IV figures), so this is
not a sweep over unknown endpoints -- that version froze the host and is gone.

  cd ~/git/a7c2/Sony-PMCA-RE
  sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/terminal_write_error.py
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

EP_OUT_INDEX = 1   # what PMCA's shell uses; 0x04 on this camera
EP_IN_INDEX = 1    # 0x83


def show_usb_error(exc: BaseException) -> None:
    print("      %s: %s" % (type(exc).__name__, exc or "(no message)"))
    for attr in ("errno", "strerror", "backend_error_code"):
        if hasattr(exc, attr):
            print("      %-18s %r" % (attr, getattr(exc, attr)))


def run(camera, args) -> None:
    driver = camera.dev.driver
    backend = driver.backend
    ep_out = driver.epOut[EP_OUT_INDEX]
    ep_in = driver.epIn[EP_IN_INDEX]
    print("using OUT %#04x / IN %#04x (the ones `shell` uses)" % (ep_out, ep_in))

    print("\nenabling the terminal...")
    camera.setTerminalEnable(True)
    try:
        print("reading first, in case the terminal is already talking:")
        got = b""
        deadline = time.time() + 1.0
        while time.time() < deadline:
            try:
                chunk = backend.read(ep_in, 0x40, 200)
            except Exception as exc:
                print("    read raised:")
                show_usb_error(exc)
                if getattr(exc, "__cause__", None):
                    show_usb_error(exc.__cause__)
                break
            if chunk:
                got += bytes(chunk)
                deadline = time.time() + 0.3
        print("    %d bytes: %r" % (len(got), got[:200]) if got else "    silent")

        print("\nsending one newline on OUT %#04x:" % ep_out)
        try:
            backend.write(ep_out, args.probe.encode())
            print("    the write went through")
        except Exception as exc:
            print("    the write raised - this is what `shell` hides:")
            show_usb_error(exc)
            cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
            if cause is not None:
                print("    underlying:")
                show_usb_error(cause)
            return

        print("\nreading the answer:")
        got = b""
        deadline = time.time() + 1.5
        while time.time() < deadline:
            try:
                chunk = backend.read(ep_in, 0x40, 200)
            except Exception:
                chunk = b""
            if chunk:
                got += bytes(chunk)
                deadline = time.time() + 0.3
        print("    %d bytes: %r" % (len(got), got[:400]) if got else "    silent")
        if not got:
            print("\n    The write is accepted but nothing answers: the terminal")
            print("    exists with no interactive subsystem behind it (ulogio's")
            print("    ISYS is 0 on this camera), which is a camera-side setting,")
            print("    not a host problem.")
    finally:
        print("\ndisabling the terminal...")
        try:
            camera.setTerminalEnable(False)
        except Exception as exc:
            print("    (disable raised: %s)" % (exc or type(exc).__name__))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", default="\n", help="what to send (default: a newline)")
    args = ap.parse_args()

    from pmca.commands.usb import senserShellCommand
    print("using pmca from %s" % PMCA_ROOT, flush=True)

    done = False

    def go(camera):
        nonlocal done
        run(camera, args)
        done = True

    senserShellCommand(complete=go)
    if not done:
        print("Camera never reached service mode; reconnect and run again.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
