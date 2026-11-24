#!/usr/bin/env python3
"""Inventory the shell/SSH related components of an unpacked ILCE-7CM2 p15.

Read-only. Takes the directory produced by fwtool.py when it unpacks
``0700_part_image/dev/nflasha15`` from an official BODYDATA.DAT and reports,
for every component this project cares about: presence, size, SHA-256 and
whether the byte image is identical to the Sony ILCE-7M4 (A7 IV) 6.02
component that the published A7 IV shell-access recipes were derived for.

The A7 IV reference digests are quoted from the public
Erlla/sony-a7m4-custom-firmware ``methods/09-shell-access/reference-layout.json``.
No Sony code or firmware is contained here, only digests.

Usage:
  python3 scripts/collect_shell_components.py <nflasha15_unpacked> \
      [--json evidence/component-inventory.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

# path inside p15 -> (role, A7 IV 6.02 sha256 or None)
COMPONENTS = {
    "sbin/sshd": ("OpenSSH daemon shipped by Sony", None),
    "bin/ssh-keygen": ("host key generator", None),
    "bin/create_host_key.sh": ("Sony wrapper that makes the ECDSA host key", None),
    "bin/get_finger_print.sh": ("Sony wrapper that prints the host key fingerprint", None),
    "bin/ssh_session_monitoring": ("session watchdog", None),
    "bin/ssh_account_lock_recorder": ("account lockout recorder", None),
    "lib/libnss_ssh.so.2": (
        "NSS module that invents the login account",
        "21c29cad2acc9af2183f81512a2ebdbc729bbf643fc41fd0cd28635944f051e4",
    ),
    "lib/libInfraSSHManager.so": ("sshd lifecycle / host key in backup", None),
    "lib/libssh2.so.1.0.1": ("SSH client library (parent/child feature)", None),
    "bin/bootin.elf": (
        "boot-time launcher, hook target for starting sshd",
        "82894d65312d1d854706589d369cbfc29d662895594d8c5b1755ad8cc9208390",
    ),
    "lib/libosal_ulogio.so": (
        "ulogio: telnetd + log filter",
        "b31f6e90f37841ab0249a36cc4b3224610f77ae8bc2b9995f9268c2c0131f474",
    ),
    "bin/ulogio": ("ulogio CLI (telnet up/down, term on/off)", None),
    "bin/ulogio.elf": ("ulogio CLI helper", None),
    "kmod/osal_ulogio.ko": ("ulogio kernel module", None),
    "lib/libsencore.so": (
        "Sony service core (Senser/Jiritsu dispatch, dlopen)",
        "f58b97548062b8c5ab819f109e7cd64b57b1724e7885ca066358a0dc4849f742",
    ),
    "lib/libJiritsu.so": ("Jiritsu service commands", None),
    "wifi-scripts/ulset.sh": ("factory ulogio filter script", None),
}

# symbols / literals whose presence decides whether a recipe is reusable
MARKERS = {
    "lib/libosal_ulogio.so": [
        "ulogio_telnetd_init",
        "ulogio_telnetd_mainloop",
        "ulogio_filter_set_telnet",
        "ulogio_filter_get_telnet",
    ],
    "lib/libsencore.so": [
        "@JIRITSU_SET_FILE",
        "@JIRITSU_SET_FILE2",
        "@JIRITSU_GET_FILE2",
        "@JIRITSU_SET_FILE_PATH",
        "@JIRITSU_FILE_DELETE",
        "@JIRITSU_MOUNT",
        "@JIRITSU_FIRMUP",
        "dlopen",
    ],
    "lib/libInfraSSHManager.so": [
        "SSHD_START_CMD",
        "/usr/sbin/sshd",
        "createKeyFromBackup",
        "/tmp_network/ssh/ssh_name_password",
    ],
    "lib/libnss_ssh.so.2": [
        "/tmp_network/ssh/ssh_name_password",
        "/bin/false",
    ],
}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("p15_root", type=pathlib.Path,
                    help="unpacked nflasha15 directory")
    ap.add_argument("--json", type=pathlib.Path, default=None)
    args = ap.parse_args()

    root: pathlib.Path = args.p15_root
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    out = {"p15_root": str(root), "components": {}}
    for rel, (role, a7iv) in COMPONENTS.items():
        path = root / rel
        entry: dict[str, object] = {"role": role, "present": path.is_file()}
        if entry["present"]:
            blob = path.read_bytes()
            digest = hashlib.sha256(blob).hexdigest()
            entry["size"] = len(blob)
            entry["sha256"] = digest
            if a7iv:
                entry["a7iv_602_sha256"] = a7iv
                entry["identical_to_a7iv_602"] = digest == a7iv
            wanted = MARKERS.get(rel)
            if wanted:
                # substring search: some markers are parts of mangled symbols
                entry["markers"] = {m: (m.encode("ascii") in blob) for m in wanted}
        out["components"][rel] = entry

    width = max(len(r) for r in COMPONENTS)
    for rel, entry in out["components"].items():
        if not entry["present"]:
            print(f"{rel:<{width}}  MISSING")
            continue
        same = entry.get("identical_to_a7iv_602")
        tag = "" if same is None else ("  [== A7 IV 6.02]" if same else "  [!= A7 IV 6.02]")
        print(f"{rel:<{width}}  {entry['size']:>9}  {entry['sha256'][:16]}…{tag}")
        for marker, ok in entry.get("markers", {}).items():
            print(f"{'':<{width}}    {'+' if ok else '-'} {marker}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
