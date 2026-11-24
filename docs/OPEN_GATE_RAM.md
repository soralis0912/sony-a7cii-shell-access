# Open gate: the on-memory route

The sensor readout-mode table was located statically in the coprocessor image
`cpapp-b.bin` (see the open-gate repository's `docs/SENSOR_TABLE.md`). What was
missing was a way to change it at runtime, so a test leaves nothing behind.
This is the preparation for that, and the state of each step.

## Why on-memory rather than on-disk

`/cp` is `/dev/nflasha8`, vfat, mounted **rw**, and `cpapp-b.bin` is an
ordinary file on it. Editing the file would be the easy route and the wrong
one: it survives a power cycle, so a bad patch is a camera that may not come
back, and the image is likely checksummed on load. Patching the loaded copy in
RAM is undone by turning the camera off, which is the property a first test
needs most.

## The signature

A 76-byte window at file offset `0xdd832e` covers both `7008x3942` records and
**occurs exactly once in the whole 18,090,880-byte image**. 38 bytes - a single
record - occurs twice, so it is not enough. The window is recorded in the
open-gate repository as `evidence/ram-signature-a7cii-201.json`, with the six
patch offsets inside it:

| offset in signature | field | old | new |
| --- | --- | --- | --- |
| +20 | record 0 vertical[2] | 2 | 8 |
| +24 | record 0 vertical[4] (v_active) | 3942 | 4672 |
| +28 | record 0 vertical[6] | 2 | 8 |
| +58 | record 1 vertical[2] | 2 | 8 |
| +62 | record 1 vertical[4] (v_active) | 3942 | 4672 |
| +66 | record 1 vertical[6] | 2 | 8 |

All six were checked against the bytes inside the signature, not just against
the image.

## Step 1 - find it in RAM. Read only.

`native/jit/jit_ogscan.c` builds a 5,856-byte payload that dumps
`/proc/cmdline` and `/proc/iomem` and, if given a range, searches it for the
signature through `/dev/mem` opened `O_RDONLY`. It maps 8 MB at a time with a
4 KB overlap so a signature crossing a window boundary is still found, and it
writes nothing but its own report.

Run it with no parameters first. Guessing a physical range before reading
`/proc/iomem` and the kernel's `memrsv=` is pointless, and the first run is
what tells us where the coprocessor's reserved region is:

```
jit_load.py native/jit/libJit_ogscan.so --run ''
jit_load.py --read /tmp/jiritsu/jit_report.txt
```

Then feed the range back in, hex, no `0x`, start on the first line and length
on the second:

```
jit_load.py native/jit/libJit_ogscan.so --run '40000000
20000000'
```

A hit gives the physical address of record 0; record 1 is 38 bytes later.

## Step 2 - write the six values. Not written yet.

Deliberately a separate payload, so that nothing which can write to `/dev/mem`
exists until step 1 has actually produced an address. Writing needs the same
mapping with `PROT_WRITE` and `MAP_SHARED`, and the question it cannot answer
on its own is whether the coprocessor re-reads the table when the movie mode
changes or only at its own startup. If only at startup, the on-memory route
needs the patch applied before the coprocessor boots, which is a different
problem from this one.

## What has to happen first

The shell is gone - `telnetd` lived in `/tmp` and the camera has been power
cycled since. Getting it back is the Jiritsu path over USB, which means
service mode, which this session has learned leaves USB dead until the next
power cycle. So the order is: power cycle, service mode, `libJit_sh.so` or
`telnetd`, then step 1.
