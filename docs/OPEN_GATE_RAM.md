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

## Step 1 - find it in RAM. Done, 2026-11-25.

`native/jit/jit_ogscan.c` dumps `/proc/cmdline` and `/proc/iomem` and searches
a physical range for the signature through `/dev/mem` opened `O_RDONLY`,
mapping 8 MB at a time with a 4 KB overlap. Run with no range it only dumps the
two files, which is the right first run: guessing a range before reading the
memory map is pointless.

All 4 GB was then scanned in one pass:

    windows mapped: 514, failed: 0, readable from 0x400000000 to 0x500000000
    hits: 5

**`/dev/mem` gives the whole of RAM, with not one window refused.** No
`STRICT_DEVMEM` stands in the way.

Five hits, and only one of them is the loaded image:

| hit | implied base | |
| --- | --- | --- |
| `0x4086a0f4c` | `0x4078c8c1e` | ordinary kernel RAM |
| `0x4086a8d5b` | `0x4078d0a2d` | ordinary kernel RAM |
| `0x40bbdcf48` | `0x40ae04c1a` | ordinary kernel RAM |
| **`0x41add832e`** | **`0x41a000000`** | **16 MB aligned, inside `memrsv=0x0BE00000@0x410200000:uc`** |
| `0x49f300f4b` | `0x49e528c1d` | inside the 3.3 GB uncached block |

`0x41add832e - 0xdd832e = 0x41a000000` exactly, and no other hit yields an
aligned base. The low bits of the address are the file offset itself. So the
coprocessor image is loaded at `0x41a000000` in the uncached reserved region,
and the two `7008x3942` records are at:

| field | physical | old | new |
| --- | --- | --- | --- |
| record 0 vertical[2] | `0x41add8342` | 2 | 8 |
| record 0 vertical[4] | `0x41add8346` | 3942 | 4672 |
| record 0 vertical[6] | `0x41add834a` | 2 | 8 |
| record 1 vertical[2] | `0x41add8368` | 2 | 8 |
| record 1 vertical[4] | `0x41add836c` | 3942 | 4672 |
| record 1 vertical[6] | `0x41add8370` | 2 | 8 |

The other four hits are copies - the file read from `/cp` sitting in the page
cache, most likely. They matter for step 2 only if the coprocessor can reload
the table from one of them.

### The USB trouble on the way was the port

Six consecutive runs failed, in six different places and progressively
earlier: library write, mode-switch timeout, library write, `authenticate`
read, `authenticate` write. With the driver finally made to name its cause it
was `USBError(5, 'Input/Output Error')` - EIO, not a timeout, so neither the
size theory nor the timeout theory was right. **Moving the cable to the Mac's
other USB-C port fixed it on the next attempt**, with the same cable and the
same camera.

Keep that in mind before rewriting any code: a service-mode session that fails
in a different place each time is a link problem, not a protocol one.

## Step 2 - write the six values. Not written yet.

Deliberately a separate payload, so that nothing which can write to `/dev/mem`
exists until step 1 has actually produced an address. It has now - see above -
so this is the next thing to write, and the first one that is not reversible by
simply reading nothing. Writing needs the same
mapping with `PROT_WRITE` and `MAP_SHARED`, and the question it cannot answer
on its own is whether the coprocessor re-reads the table when the movie mode
changes or only at its own startup. If only at startup, the on-memory route
needs the patch applied before the coprocessor boots, which is a different
problem from this one.

## No shell needed

Step 1 wanted a shell and turned out not to need one. `jit_load.py` sends the
payload and reads `/tmp/jiritsu/jit_report.txt` back in the same service-mode
session, so one USB session does the whole thing - no `telnetd`, no Wi-Fi.

What is still true is that a service-mode session leaves USB dead until the
camera is power cycled, so each run costs one power cycle. Make each one
count.

## Step 2 - the patch payload

`native/jit/jit_ogpatch.c`. Parameters in `/tmp/jiritsu/DIAC.csv`: the physical
address on the first line, and on the second `patch`, `restore`, or nothing at
all. **Nothing is the default and writes nothing.**

Before it writes, it re-reads the 76-byte signature at that address and refuses
unless every byte outside the six fields still matches and all six fields hold
either the original or the patched value. A wrong address costs a report rather
than a damaged image - verified offline, where shifting the address by a single
byte is caught at +0.

Because that check is in the payload, there is no point spending a separate
service-mode session on a dry run: `patch` either does the right thing or
reports why it did nothing.

### The values are Sony's own

Patching the two `7008x3942` records turns their vertical group into
`[34, 24, 8, 8, 4672, 8, 8, 0]`, **byte for byte the vertical group of the
firmware's own `7008x4672` record** at `0xdd82e2`. Nothing here is invented;
the full-height numbers are copied from the record Sony already ships. Checked
offline against `cpapp-b.bin`, along with the facts that only the six fields
change and that `restore` returns the original 76 bytes exactly.

### Why the cache matters

After writing, the payload cleans the data cache over the range with
`DC CIVAC` and a `DSB`. The mapping through `/dev/mem` may be cached while the
coprocessor reads the same DRAM for itself, and a change the coprocessor never
sees looks exactly like a change that does nothing. The region is marked `:uc`
in `memrsv=`, which suggests it is uncached anyway, but the flush costs
nothing and removes the doubt.

### What it still cannot answer

Whether the coprocessor reads this table on a mode change or only at its own
startup. If only at startup, the patch will take in memory - the read-back will
confirm the bytes - and nothing will change on screen. That would not be a
failure of the patch; it would mean the on-memory route needs the write to
happen before the coprocessor boots, which is a different problem.

The four other copies of the signature found in ordinary kernel RAM are the
other thing to watch: if the coprocessor can reload from one of those, patching
only the loaded image is not enough.

## The patch takes, 2026-11-25

    address 0x41add832e  mode patch
    signature matches outside the six fields
    field values now:
      +20 = 2      (original)
      +24 = 3942   (original)
      +28 = 2      (original)
      +58 = 2      (original)
      +62 = 3942   (original)
      +66 = 2      (original)
    written; reading back:
      +20 = 8      ok
      +24 = 4672   ok
      +28 = 8      ok
      +58 = 8      ok
      +62 = 4672   ok
      +66 = 8      ok

Two things worth taking from that beyond the obvious. All six fields read as
**original** before the write, so `0x41add832e` is the same address after a
power cycle - the coprocessor image is loaded at a fixed reserved address, as
`memrsv=` implies, and does not need finding again. And writing through
`/dev/mem` to the uncached reserved region works, read-back included.

What this does **not** yet say is whether the coprocessor acts on it. The
output-size table at `cpapp-b.bin:0xbefe38` was deliberately left alone, so the
sensor is now told to read 4672 lines while the rest of the pipeline still
expects 3942. A squashed or broken 4K image would therefore be a *success*
signal - it would prove the table is read live. An unchanged image means the
coprocessor read the table at its own startup and a later write cannot reach
it.

## The coprocessor reads the table only at its own init

The patch takes and stays, and the picture does not change. Established over
one boot, from the shell, with no power cycle in between:

- the six fields still read 8 / 4672 / 8 / 8 / 4672 / 8 well after the write
- switching the camera into 4K movie mode does not revert them
- nothing restores them from `/cp`
- and the image on screen is unchanged

The four other hits the scan found turned out to be transient. Re-read later
they hold unrelated data - `25705 x 10`, zeros, `0 x 1864` - so they were
buffers that happened to contain a copy at scan time, not stable copies. The
only real one is at `0x41add832e`, and it stays patched.

So the table is consulted when the coprocessor initialises, and a write
afterwards cannot reach it.

### `dd` is enough, and the shell beats service mode here

`/dev/mem` is reachable from the shell. Page-align the seek, or `dd` will try
to read and discard 17 GB:

```
dd if=/dev/mem bs=4096 skip=$((0x41add8000 / 4096)) count=1 | busybox xxd -p
```

This matters more than it sounds. A service-mode session leaves USB dead until
a power cycle, and a power cycle erases the volatile patch - so inspecting the
patch over USB is impossible by construction. Over Wi-Fi the shell outlives
everything and the patch can be examined, re-examined and changed within one
boot. Spend the one service-mode session on starting `telnetd`, then work over
the network.

(When parsing `xxd -p` output off a telnetd pty, keep only lines that are
entirely hex. The shell's own prompt, `/usr/share/app # cat ...`, contributes
`a`, `c`, `e`, `d`, `f` and `b` to a naive filter - which is how a clean page
first came back as 4104 bytes of nonsense.)

### What the coprocessor is

`pci_ep_cp` is loaded, with `pcieatu`, `pcie_if`, `ldec` and `mcmn_drv`: the
coprocessor is a **PCI endpoint**, which is what `dffe0000-dffeffff :
0000:00:00.0` in `/proc/iomem` is. But `pci_ep_cp.ko` is 6,496 bytes with only
`probe` and `shutdown` - a stub, not the image loader. `bootin.elf` turns out
to be an app launcher. The only thing in the root filesystem that names
`/image_nflasha8` is `libInfraMediaCommon.so`. No runtime interface for
reloading or resetting the coprocessor has been found.

## What is left: get there before the coprocessor does

Two ways, and only one of them is currently open.

**Patch `/cp/cpapp-b.bin`.** Eight bytes, at offsets already known, on a
partition mounted rw. The coprocessor would then read the full-height table at
its own init. It persists until restored, which is the whole point and also the
whole risk.

On verification: the update package's `part_image.sum` does record a CRC32 for
the partition -

    0,91eede9f,017f0800,...,dev/nflasha8,

\- but every tool that checks it (`uc_crc32sum.elf`, `us_crc32sum.sh` and the
rest) lives inside `bin/udtrbody.bin_unpacked`, the **updater** body, and none
of them is in the normal root filesystem. So the CRC looks like an
update-time check rather than a boot-time one. That is an observation, not a
proof.

What to weigh before doing it:

- the 8 bytes can be restored from the shell, and re-running Sony's own 2.01
  update rewrites the partition and the CRC with it
- but if the coprocessor refuses to start, whether a shell or service mode can
  still be reached depends on how much of `im.elf` comes up without it, and
  that is unknown
- the output-size table at `0xbefe38` is **not** part of this patch, so the
  sensor would be read at 4672 lines while the pipeline still expects 3942.
  Deliberately incoherent is fine for a volatile test and a poor idea for a
  persistent one: for this route both tables should be settled first, and the
  open-gate repository still has the readout length (2011 -> ?) open

**Reset the coprocessor at runtime.** Nothing found yet. The driver is a stub
and the loader appears to run before any of this is reachable.
