#!/usr/bin/env python3
"""Push a plain-ASCII file into the camera over the busybox telnetd shell.

    CAMERA_HOST=192.168.0.10 telnet_put.py <local file> <remote path> [wait_s]

Turns the pty echo off, runs `cat > <remote>`, streams the bytes, sends ^D,
then prints the remote size and md5 so the transfer can be checked against
the local file. Only ASCII files: no IAC (0xff) escaping is done.
"""
import hashlib, os, socket, sys, time

HOST = os.environ.get("CAMERA_HOST", "192.168.1.1")
PORT = int(os.environ.get("CAMERA_PORT", "2323"))
local, remote = sys.argv[1], sys.argv[2]
WAIT = int(sys.argv[3]) if len(sys.argv) > 3 else 120

data = open(local, "rb").read()
if b"\xff" in data or max(data) > 127:
    sys.exit("not plain ASCII; refusing to stream over telnet")
print("local  %s  %d bytes  md5 %s" % (local, len(data), hashlib.md5(data).hexdigest()))

end = time.time() + WAIT
sock = None
while time.time() < end:
    try:
        sock = socket.create_connection((HOST, PORT), timeout=3)
        break
    except OSError:
        time.sleep(1)
if sock is None:
    sys.exit("camera not reachable at %s:%d" % (HOST, PORT))

sock.settimeout(1.0)
time.sleep(0.4)
try:
    while sock.recv(65536):
        pass
except OSError:
    pass

sock.sendall(b"busybox stty -echo\ncat > " + remote.encode() + b"\n")
time.sleep(1.0)
try:
    while sock.recv(65536):
        pass
except OSError:
    pass

sent = 0
t0 = time.time()
sock.settimeout(60)
while sent < len(data):
    n = sock.send(data[sent:sent + 4096])
    sent += n
sock.sendall(b"\x04")                     # ^D ends cat
print("streamed %d bytes in %.1fs" % (sent, time.time() - t0))

time.sleep(1.0)
sock.sendall(b"busybox stty echo\n"
             b"busybox md5sum " + remote.encode() + b"\n"
             b"ls -l " + remote.encode() + b"\n"
             b"busybox df " + os.path.dirname(remote).encode() + b"\n"
             b"echo __TPUTDONE__\n")
sock.settimeout(2.0)
buf = b""
end = time.time() + 60
while time.time() < end:
    try:
        chunk = sock.recv(65536)
    except socket.timeout:
        if b"__TPUTDONE__" in buf:
            break
        continue
    except OSError:
        break
    if not chunk:
        break
    buf += chunk
    if buf.count(b"__TPUTDONE__") >= 2:
        break
sock.close()
sys.stdout.write(buf.decode("utf-8", "replace"))
