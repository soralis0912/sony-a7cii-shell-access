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

## How the camera actually finds user LUTs

The menu's custom-LUT slots all read "none" even with a correctly formatted
970 KB `.cube` sitting in `/usr/data/lut`. The four entries that *are* named and
selectable are the stock `S709`, `S709C`, `r709` and `r709C` - the four files
that ship in that directory. So the camera does not scan the directory for user
LUTs; it looks for fixed names.

`lib/appFw.so` in the root filesystem (100 MB, stripped) holds the proof. Both
path formats are referenced from one pair of thunks, at 0x302040c and
0x3020430:

    0x0302040c  mov   x5, x1
    0x03020410  adrp  x3, #0x4bfa000
    0x03020414  adrp  x2, #0x4bfa000
    0x03020418  add   w4, w0, #1
    0x0302041c  add   x3, x3, #0x3d3      ; "/usr/data/lut"
    0x03020420  add   x2, x2, #0x3e1      ; "%s/LUT%03d.cube"
    0x03020424  mov   x0, x5
    0x03020428  mov   x1, #0x1a
    0x0302042c  b     #0x165ded0          ; snprintf

So the filename is `/usr/data/lut/LUT%03d.cube`, and `add w4, w0, #1` means the
number is the slot index **plus one** - slot 0 is `LUT001.cube`. The buffer size
`#0x1a` is 26, exactly `strlen("/usr/data/lut/LUT001.cube") + 1`, which confirms
the composition. The second thunk is identical but uses `%s/LUT%03d.LUT` at
0x4bfa3b2, so a second extension exists alongside the text one.

The neighbouring strings name the rest of the mechanism:

    0x4bfa390  mount_lut_folder():NG
    0x4bfa3a6  %lf %lf %lf                 <- the data-line parser
    0x4bfa3b2  %s/LUT%03d.LUT
    0x4bfa3c1  /usr/data/lut/AAA
    0x4bfa3d3  /usr/data/lut
    0x4bfa3e1  %s/LUT%03d.cube
    0x4bfa3f1  /Private/Sony/PRO/LUT       <- the import source, on the card
    0x4bfa407  SL3SG3CtoR709-800.cube

`%lf %lf %lf` is how each line is read, so the six-decimal formatting is not
load-bearing - any `scanf`-parseable triple works.

### There is a supported import path

`/Private/Sony/PRO/LUT` is a directory on the **memory card**. Putting a `.cube`
there and using the camera's own LUT import menu is the route Sony built, and
it is what writes the backup properties the slots depend on:

    BKID_APP_IS_EXIST_USER_LUT<n>              IS_EXIST_USER_LUT_EMPTY / _EXIST
    BKID_APP_USER_LUT_FILE_ID<n>
    BKID_APP_USER_LUT_ATTR_INPUT_GAMUT<n>
    BKID_APP_USER_LUT_ATTR_OUTPUT_PROCAM<n>
    BKID_APP_USER_LUT_ATTR_AE_LEVEL_OFFSET<n>

On a FAT card the path is `PRIVATE/SONY/PRO/LUT`. Other strings in the same
area - `CUBE_FILE_OPERATION_DESTINATION_MEDIA`, `..._CLOUD_PRIVATE`,
`..._CLOUD_SHARE`, `EVENT_REMOTE_CUBE_FILE_CLOUD_DOWNLOAD_LIST` - show the
import can also come from Creators' Cloud.

So testing a generated LUT needs no service mode and no shell at all. The
shell route is only interesting for the question below.

## What is still open

Whether writing `/usr/data/lut/LUT001.cube` directly and cold-booting makes
slot 0 register itself, or whether `BKID_APP_IS_EXIST_USER_LUT0` has to be set
first. `test.cube` proved the directory is writable but told us nothing about
this, because the name was never one the camera looks for.

The fallback experiment avoids registration entirely: overwrite `r709C.cube`
with the `swap` LUT, keeping the original, and see whether selecting the
*stock* entry gives swapped colour. That tests the rendering pipeline on its
own.

```
cp /usr/data/lut/r709C.cube /usr/data/lut/r709C.cube.orig
```

`native/jit/jit_lut.c` generates the LUT on the camera instead, for when only
the Jiritsu path is available and there is no shell to stream through.
