# Custom LUTs

Verified on an ILCE-7CM2, firmware 2.01. The file is on the camera; whether
the menu offers it is **not yet confirmed** (see "What is still open").

## `/usr/data/lut` is a writable partition of its own

```
/dev/nflasha30 on /usr/data/lut type vfat (rw,dirsync,noatime,
    fmask=0022,dmask=0022,codepage=437,iocharset=ascii,
    shortname=mixed,posix_attr,avoid_dlink,errors=remount-ro)
```

Sony gave the LUT store its own flash partition, mounted read-write. The four
files that ship with the camera are all dated 2021-12-27:

| file | bytes |
| --- | --- |
| `S709.cube` | 970355 |
| `S709C.cube` | 970360 |
| `r709.cube` | 970314 |
| `r709C.cube` | 970314 |

## The format

A plain Adobe `.cube`, 33 points per axis, LF line endings, ASCII only:

```
LUT_3D_SIZE 33
0.000000 0.000000 0.000000
0.004155 0.000000 0.000000
...
```

One header line and 35937 data lines, so 35938 lines and 970314 bytes for a
LUT whose values all take six decimals. Red varies fastest, then green, then
blue. `S709.cube` begins with two `#` comment lines, so comments are allowed.

`scripts/gen_lut.py` writes a file of exactly that shape. In `swap` mode it is
an identity LUT with red and blue exchanged, which is the point: a wrong colour
is visible at a glance, where a subtle curve would not be.

```
$ python3 scripts/gen_lut.py swap test.cube
test.cube  970314 bytes  35938 lines
```

970314 bytes is the stock `r709.cube` size to the byte.

## Getting the file onto the camera

`scripts/telnet_put.py` streams it through the root shell. Over the camera's
Wi-Fi the whole 970 KB took **0.6 s**, and the MD5 matched on both sides:

```
local  test.cube  970314 bytes  md5 2327d620465827e117c1396a866b327e
streamed 970314 bytes in 0.6s
2327d620465827e117c1396a866b327e  /usr/data/lut/test.cube
-rwxr-xr-x    1 root     0  970314 Jan  1 01:25 /usr/data/lut/test.cube
```

It works because the data is pure ASCII: no byte is 0xff, so no telnet IAC
escaping is needed, and no byte is CR, so the pty's line discipline has nothing
to translate. The script refuses any file that is not plain ASCII rather than
corrupting it. TCP back-pressure handles the rate — the pty blocks telnetd,
telnetd stops reading the socket, and the sender stalls instead of dropping
data.

The mode is set to 755 afterwards so the file is indistinguishable from the
four Sony ones.

## Calling busybox applets

`busybox --list` on this camera has 130 applets, but `/bin` holds symlinks for
only some of them. `md5sum`, `wc`, `xxd`, `tail`, `df`, `head` and `id` are all
compiled in and all report `not found` when invoked bare — they must be called
as `busybox md5sum` and so on. This is the same trap as `telnetd`.

`tr` is absent from the list itself, so no spelling of it works.

## What is still open

Whether the menu lists a LUT that was merely dropped into the directory. The
feature-research repository's BKID inventory has `BKID_APP_IS_EXIST_USER_LUT0`
through `49`, plus `USER_LUT_FILE_ID` and `USER_LUT_ATTR_*` — 50 slots of
backup properties. If the camera trusts that index instead of reading the
directory, a new file will not appear until a slot is registered, and the
import path in the menu is what writes those slots.

The fallback experiment avoids the question entirely: overwrite `r709C.cube`
with the `swap` LUT, keeping the original, and see whether selecting the
*stock* entry gives swapped colour. That tests the rendering pipeline without
needing registration.

```
cp /usr/data/lut/r709C.cube /usr/data/lut/r709C.cube.orig
```

`native/jit/jit_lut.c` generates the LUT on the camera instead, for when only
the Jiritsu path is available and there is no shell to stream through.
