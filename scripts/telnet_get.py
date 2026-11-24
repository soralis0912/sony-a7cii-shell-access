#!/usr/bin/env python3
"""Pull a plain-ASCII file off the camera through the busybox telnetd shell.

    CAMERA_HOST=192.168.0.10 telnet_get.py <remote path> <local path>

Turns the pty echo off, cats the file, strips the CR the line discipline adds
on output, and checks the result against the camera's own md5sum. Text files
only - a binary would be mangled by the pty and by IAC escaping.
"""
import hashlib, os, re, socket, sys, time

HOST = os.environ.get("CAMERA_HOST", "192.168.1.1")
PORT = int(os.environ.get("CAMERA_PORT", "2323"))
remote, local = sys.argv[1], sys.argv[2]
WAIT = int(sys.argv[3]) if len(sys.argv) > 3 else 120
BEGIN = b"__GETBEGIN__"
END = b"__GETEND__"

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

sock.sendall(b"busybox stty -echo\nbusybox md5sum " + remote.encode() + b"\n")
time.sleep(1.5)
head = b""
try:
    while True:
        d = sock.recv(65536)
        if not d:
            break
        head += d
except socket.timeout:
    pass
m = re.search(rb"([0-9a-f]{32})\s", head)
remote_md5 = m.group(1).decode() if m else None
print("camera md5: %s" % (remote_md5 or "(not reported)"))

# bracket the content, because the shell prints its prompt between the two
# commands and that prompt would otherwise land in the file - 17 bytes of
# "/usr/share/app # " was exactly the error the first version made
sock.sendall(b"echo " + BEGIN + b"; cat " + remote.encode()
             + b"; echo " + END + b"\n")
buf = b""
sock.settimeout(5.0)
end = time.time() + 300
while time.time() < end:
    try:
        d = sock.recv(65536)
    except socket.timeout:
        if END in buf:
            break
        continue
    except OSError:
        break
    if not d:
        break
    buf += d
    if END in buf:
        break
sock.sendall(b"busybox stty echo\n")
sock.close()

if BEGIN not in buf or END not in buf:
    sys.exit("did not see both markers; the file was not captured")
body = buf.split(BEGIN, 1)[1].split(END, 1)[0]
body = body.replace(b"\r\n", b"\n")
body = body.lstrip(b"\n")          # the newline after the BEGIN echo
open(local, "wb").write(body)
local_md5 = hashlib.md5(body).hexdigest()
print("saved %s  %d bytes  md5 %s" % (local, len(body), local_md5))
if remote_md5:
    print("MATCH" if local_md5 == remote_md5 else "MISMATCH - do not rely on this copy")
    sys.exit(0 if local_md5 == remote_md5 else 1)
