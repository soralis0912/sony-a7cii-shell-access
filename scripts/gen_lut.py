#!/usr/bin/env python3
"""Generate a 33^3 .cube LUT matching the camera's stock format exactly."""
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "swap"
out = sys.argv[2] if len(sys.argv) > 2 else "test.cube"

lines = ["LUT_3D_SIZE 33"]
for k in range(33):
    for j in range(33):
        for i in range(33):
            r, g, b = i * 31250, j * 31250, k * 31250   # millionths
            if mode == "swap":
                r, b = b, r
            elif mode == "green":
                g = g // 5
            elif mode == "identity":
                pass
            else:
                sys.exit("unknown mode " + mode)
            lines.append(" ".join("%d.%06d" % divmod(v, 1000000) for v in (r, g, b)))

data = "\n".join(lines) + "\n"
open(out, "w", newline="\n").write(data)
print("%s  %d bytes  %d lines" % (out, len(data), data.count("\n")))
assert "\0" not in data and "\r" not in data
assert max(map(ord, data)) < 128
