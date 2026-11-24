#!/usr/bin/env python3
"""Run a script on the camera's busybox telnetd shell (telnetd -l /bin/sh).

Reads the script on stdin, waits for the camera to appear on the network,
runs it in a single connection and prints everything the shell said.

    CAMERA_HOST=192.168.0.10 telnet_shell.py [wait_s] [run_s] < script.sh

Start telnetd on the camera first, through the Jiritsu code path:
    busybox telnetd -l /bin/sh -p 2323
It lives in /tmp, so it is gone after a power cycle. Nothing is written to
non-volatile storage to get here.
"""
import os, socket, sys, time

# the camera's address on your network
HOST = os.environ.get("CAMERA_HOST", "192.168.1.1")
PORT = int(os.environ.get("CAMERA_PORT", "2323"))
WAIT = int(sys.argv[1]) if len(sys.argv) > 1 else 10      # seconds to wait for the camera
RUN  = int(sys.argv[2]) if len(sys.argv) > 2 else 120     # seconds to let the script run
MARK = b"__JITDONE__"

script = sys.stdin.buffer.read()

deadline = time.time() + WAIT
sock = None
while time.time() < deadline:
    try:
        sock = socket.create_connection((HOST, PORT), timeout=3)
        break
    except OSError:
        time.sleep(1)
if sock is None:
    sys.stderr.write("camera not reachable at %s:%d after %ds\n" % (HOST, PORT, WAIT))
    sys.exit(2)

sock.settimeout(1.0)
time.sleep(0.4)
try:                     # drain the banner and any telnet negotiation
    while sock.recv(65536):
        pass
except OSError:
    pass

sock.sendall(script.rstrip(b"\n") + b"\necho " + MARK + b"\n")

buf = b""
end = time.time() + RUN
while time.time() < end:
    try:
        chunk = sock.recv(65536)
    except socket.timeout:
        continue
    except OSError:
        break
    if not chunk:
        break
    buf += chunk
    # the marker echoes once in the command line, once as output
    if buf.count(MARK) >= 2:
        break
sock.close()
sys.stdout.write(buf.decode("utf-8", "replace"))
if buf.count(MARK) < 2:
    sys.stderr.write("\n[script did not finish within %ds]\n" % RUN)
    sys.exit(3)
