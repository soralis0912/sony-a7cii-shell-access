#!/usr/bin/env python3
"""One read-only pass over an ILCE-7CM2 in service mode, into a report file.

Everything here reads. Nothing is written to the backup, no file is written to
the camera, and no setting is changed. The single state-touching call is the
terminal-change command sent with the value 0 ("terminal off"), which is what
the camera already believes and is the cheapest way to learn whether the
terminal gate is open.

It collects, in one go, what a first hands-on session needs:

  1. the device properties PMCA's `info` prints (model, backup region, ...)
  2. which service dispatch table answers, i.e. the privilege level
  3. the backup properties this project cares about, by name
  4. whether the SSH host key property exists (length and digest only -- the
     key bytes are never printed or saved)
  5. the files that decide how much work root SSH needs, read through the
     Jiritsu path that is confirmed working on this camera (category 0x1001,
     SET_FILE_PATH 0x400f then GET_FILE2 0x4011, with ../../ to leave
     /tmp/jiritsu). Senser FileControl is tried too, as a second opinion.

Run it from inside a Sony-PMCA-RE checkout:

  cd ~/git/a7c2/Sony-PMCA-RE
  sudo ./venv/bin/python ~/git/a7c2/sony-a7cii-shell-access/scripts/survey_readonly.py

Then paste the report. Mind the two warnings it prints: the host key digest is
fine to share, the key is not, and /etc/passwd may carry password hashes.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import pathlib
import sys

# property id -> name, from the sibling feature-research inventory
PROPERTIES = [
    (0x02CF1700, "BKID_APP_SETTING_MODE_SHUTTER", "00"),
    (0x02CF1702, "BKID_APP_SETTING_SHUTTER_ANGLE", "10"),
    (0x02CF101D, "BKID_APP_SETTING_LOG_SHOOTING", "00"),
    (0x02CF19F0, "BKID_APP_SETTING_STILL_LOG_SHOOTING", "00"),
    (0x02CF102D, "BKID_APP_SETTING_SELECT_LUT", "01"),
    (0x02CF1021, "BKID_APP_SETTING_EMBED_LUT_FILE", "00"),
    (0x02CF1030, "BKID_APP_SETTING_APPLY_LUT", "00"),
    (0x02CF1961, "BKID_APP_SETTING_DE_SQUEEZE_DISP", "00"),
    (0x02CF1193, "BKID_APP_EXTERN_DE_SQUEEZE_DISP", "00"),
    (0x02CF01FC, "BKID_APP_SETTING_ASPECT_RATIO", None),
    (0x02CF184A, "BKID_APP_PARENT_CHILD_SERVER_CAMERA_SSH_MODE0", "00"),
    (0x02CF185D, "BKID_APP_PARENT_CHILD_SERVER_CAMERA_SSH_INFO0", "00"),
    (0x02CF18A9, "BKID_APP_PARENT_CHILD_SERVER_CAMERA_SSH_USERNAME0", "00" * 17),
]

# the host private key; read for its length only
HOST_KEY_ID = 0x03000000
HOST_KEY_LEN = 600

# Jiritsu, category 0x1001. Only the read commands are used here.
JIRITSU_CATEGORY = 0x1001
JIRITSU_SET_FILE_PATH = 0x400F
JIRITSU_GET_FILE2 = 0x4011

# (path, show contents?). The service builds paths under /tmp/jiritsu, so an
# absolute target is reached by prefixing ../../ -- the same thing the probe
# that worked on 2026-11-24 did.
FILES = [
    ("/usr/share/pmbp/DeviceInfo.xml", True),   # known-good control
    ("/etc/ssh/sshd_config", True),
    ("/etc/nsswitch.conf", True),
    ("/etc/passwd", False),
    ("/setting/ulogio.bin", False),
]
CONTROL_SHA256 = "e44713178fad970870ead845c93abdfcf150c418de11b306da91f2d09d67c1b7"

SAFE_TEXT = 4096


class Report:
    def __init__(self, path: pathlib.Path | None):
        self.lines: list[str] = []
        self.path = path

    def __call__(self, text: str = "") -> None:
        print(text, flush=True)
        self.lines.append(text)

    def save(self) -> None:
        if self.path:
            self.path.write_text("\n".join(self.lines) + "\n")
            print("\nreport written to %s" % self.path, flush=True)


def jiritsu_read(camera, path: str):
    """Fetch one file read-only: SET_FILE_PATH then GET_FILE2.

    The service resolves paths under /tmp/jiritsu, so an absolute path is
    reached with a ../../ prefix. Returns (data, None) or (None, exception).
    """
    target = b"../.." + path.encode("latin1")
    try:
        camera._sendAdjustControlPacket(
            JIRITSU_CATEGORY, JIRITSU_SET_FILE_PATH, b"\x00" + target)
        response = camera._sendAdjustControlPacket(
            JIRITSU_CATEGORY, JIRITSU_GET_FILE2, b"\x00\xff\x00")
    except Exception as exc:
        return None, exc
    if len(response) < 4:
        return None, RuntimeError("response shorter than its 4-byte status")
    status = int.from_bytes(response[:4], "little")
    if status:
        return None, RuntimeError("inner status 0x%08x" % status)
    return response[4:], None


def try_call(say, label, fn):
    try:
        value = fn()
    except Exception as exc:
        say("  %-34s refused (%s)" % (label, exc))
        return None, exc
    say("  %-34s ok" % label)
    return value, None


def survey(camera, say, out_dir: pathlib.Path) -> None:
    say("# ILCE-7CM2 read-only service-mode survey")
    say("# %s" % datetime.datetime.now().isoformat(timespec="seconds"))
    say()

    say("## 1. device properties")
    try:
        from pmca.platform.backend.senser import SenserPlatformBackend
        from pmca.platform.properties import PropertyInterface
        backend = SenserPlatformBackend(camera)
        for pid, desc, value in PropertyInterface(backend).getProps():
            say("  %-22s %s" % (desc + ":", value))
    except Exception as exc:
        say("  could not read properties: %s" % exc)
    say()

    say("## 2. service dispatch tables")
    adjust, _ = try_call(say, "0x40 AdjustControl",
                         lambda: camera.readBackup(0x02CF1700))
    product, _ = try_call(say, "0x10 ProductInfo", camera.readHasp)
    terminal, _ = try_call(say, "terminal gate (0x00f1, value 0)",
                           lambda: camera._sendProductInfoPacket(
                               *camera.SONY_PRODUCT_INFO_TERM_CHANGE, bytes([0])))
    if terminal is not None:
        level, code = "A", 3
    elif product is not None:
        level, code = "B", 2
    elif adjust is not None:
        level, code = "C", 1
    else:
        level, code = "none", 0
    say()
    say("  service level: %s (adjCodeLevel %d)" % (level, code))
    if level == "A":
        say("  the terminal gate is open: `shell` in the PMCA service shell and")
        say("  TestMode/Jiritsu should both work. Nothing was written to get here.")
    elif level in ("B", "C"):
        say("  the gate is closed, and TestMode (0xff00) is only in level A's table.")
    say()

    say("## 3. backup properties")
    for pid, name, expected in PROPERTIES:
        try:
            value = camera.readBackup(pid)
        except Exception as exc:
            say("  %#010x %-52s refused (%s)" % (pid, name, exc))
            continue
        hexed = value.hex()
        note = ""
        if expected is not None:
            note = "  (firmware default %s)" % expected if hexed != expected else "  (= default)"
        say("  %#010x %-52s %s%s" % (pid, name, hexed, note))
    say()

    say("## 4. SSH host key property (length and digest only)")
    try:
        key = camera.readBackup(HOST_KEY_ID)
        digest = hashlib.sha256(key).hexdigest()
        stripped = key.rstrip(b"\x00")
        say("  %#010x present: %d bytes (expected %d), %d non-zero"
            % (HOST_KEY_ID, len(key), HOST_KEY_LEN, len(stripped)))
        say("  sha256 %s" % digest)
        say("  starts with PEM header: %s"
            % ("yes" if stripped[:5] == b"-----" else "no"))
        say("  NOTE: the key itself is this camera's private host key. It is not")
        say("        printed or saved here. Do not publish it.")
    except Exception as exc:
        say("  %#010x refused (%s)" % (HOST_KEY_ID, exc))
    say()

    say("## 5. file reads through Jiritsu (category 0x1001)")
    say("  This path is confirmed working on an ILCE-7CM2: the first entry is the")
    say("  file the 2026-11-24 probe returned, so it doubles as a control.")
    say("  Read commands only. SET_FILE (0x4007) and the delete and format")
    say("  commands sit in the same category and are not sent.")
    control_ok = None
    for path, show in FILES:
        data, exc = jiritsu_read(camera, path)
        if exc is not None:
            say("  %-34s refused (%s)" % (path, exc))
            if path == FILES[0][0]:
                control_ok = False
            continue
        digest = hashlib.sha256(data).hexdigest()
        extra = ""
        if path == FILES[0][0]:
            control_ok = digest == CONTROL_SHA256
            extra = "  (control: %s)" % ("matches the firmware file" if control_ok
                                         else "DOES NOT match the firmware file")
        say("  %-34s %d bytes  sha256 %s%s" % (path, len(data), digest, extra))
        local = out_dir / path.strip("/").replace("/", "_")
        local.write_bytes(data)
        say("      saved to %s" % local)
        if show and len(data) <= SAFE_TEXT:
            say("      ---")
            for line in data.decode("latin1").splitlines():
                say("      %s" % line)
            say("      ---")
        elif not show:
            say("      contents not printed (may hold password hashes or binary)")
    if control_ok is False:
        say()
        say("  The control file did not come back as expected. Treat the rest of")
        say("  this section as unreliable.")
    say()

    say("## 6. Senser FileControl reads (second opinion)")
    say("  PFUNC 0xff01 is in none of the level tables, so these should fail.")
    for path, _ in FILES[:2]:
        buf = io.BytesIO()
        try:
            camera.readFile(path, buf)
        except Exception as exc:
            say("  %-34s refused (%s)" % (path, exc))
            continue
        say("  %-34s %d bytes -- FileControl works, which the static analysis"
            % (path, len(buf.getvalue())))
        say("      did not predict. Record it.")
    say()

    say("## what to do with this")
    if level == "A":
        say("  level A: the terminal gate is open, so `shell` is the next step")
        say("  (writes nothing, reverts on exit).")
    else:
        say("  level B/C: the USB terminal is out of reach, but Jiritsu is not -")
        say("  it rides on AdjustControl, which every level answers. If section 5")
        say("  returned files, the write side (SET_FILE 0x4007) is the route to")
        say("  look at next, starting in a volatile directory.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=None,
                    help="report file (default a7cii-survey-<date>.txt here)")
    ap.add_argument("--dir", type=pathlib.Path, default=pathlib.Path("."),
                    help="where to save any file the camera returns")
    args = ap.parse_args()

    out = args.out or pathlib.Path(
        "a7cii-survey-%s.txt" % datetime.date.today().isoformat())
    args.dir.mkdir(parents=True, exist_ok=True)

    try:
        from pmca.commands.usb import senserShellCommand
    except ImportError:
        print("Run this from a Sony-PMCA-RE checkout so that `pmca` is importable.",
              file=sys.stderr)
        return 2

    report = Report(out)
    done = False

    def collect(camera):
        nonlocal done
        survey(camera, report, args.dir)
        done = True

    try:
        senserShellCommand(complete=collect)
    finally:
        report.save()
    if not done:
        print("Camera never reached service mode; reconnect and run again.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
