/*
 * libJit_ogpatch.so - change the sensor readout-mode table in the running
 * camera's memory, so that the 4K window reads the sensor's full height.
 *
 * Volatile by design. The coprocessor image lives in a reserved DRAM region
 * and this writes the loaded copy, not the file in /cp, so a power cycle
 * undoes everything. Patching /cp/cpapp-b.bin would persist, and a camera
 * that will not boot is not worth the convenience.
 *
 * Parameters from /tmp/jiritsu/DIAC.csv, one per line:
 *     line 1   physical address of the signature, hex (0x41add832e here)
 *     line 2   "patch" writes the new values, "restore" writes the old ones.
 *              Anything else, including an empty line, only checks and
 *              reports - which is the default on purpose.
 *
 * Before writing anything it re-reads the 76-byte signature at that address
 * and refuses unless every byte outside the six fields matches and all six
 * fields hold the values it expects to replace. A wrong address therefore
 * costs a report, not a corrupted image.
 *
 * After writing it cleans the data cache over the range with DC CIVAC: this
 * mapping may well be cached while the coprocessor reads the same DRAM
 * directly, and a change the coprocessor never sees is indistinguishable from
 * a change that does nothing.
 *
 * Build:  aarch64-elf-gcc -shared -fPIC -nostdlib -O1 -o libJit_ogpatch.so jit_ogpatch.c
 */

#define SYS_openat   56
#define SYS_read     63
#define SYS_write    64
#define SYS_close    57
#define SYS_mmap    222
#define SYS_munmap  215
#define SYS_msync   227

#define AT_FDCWD     (-100)
#define O_RDONLY     00
#define O_RDWR       02
#define O_WRONLY     01
#define O_CREAT      0100
#define O_TRUNC      01000
#define PROT_READ    0x1
#define PROT_WRITE   0x2
#define MAP_SHARED   0x01
#define MAP_FAILED   ((void *)-1)
#define MS_SYNC      4

#define REPORT  "/tmp/jiritsu/jit_report.txt"
#define PARAMS  "/tmp/jiritsu/DIAC.csv"

/* 76 bytes from cpapp-b.bin:0xdd832e - unique in the image */
static const unsigned char SIG[] = { 0x10,0x00,0x0c,0x00,0x0c,0x00,0x60,0x1b,0x0c,0x00,0x04,0x00,0x00,0x00,0x00,0x00,0x22,0x00,0x18,0x00,0x02,0x00,0x08,0x00,0x66,0x0f,0x08,0x00,0x02,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x10,0x00,0x0c,0x00,0x0c,0x00,0x60,0x1b,0x0c,0x00,0x04,0x00,0x00,0x00,0x00,0x00,0x22,0x00,0x18,0x00,0x02,0x00,0x08,0x00,0x66,0x0f,0x08,0x00,0x02,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00 };
#define SIGLEN (sizeof SIG)

/* the six u16 fields, as offsets inside the signature */
static const struct { unsigned short at, old, nw; } FIELD[] = {
    { 20, 2, 8 }, { 24, 3942, 4672 }, { 28, 2, 8 },
    { 58, 2, 8 }, { 62, 3942, 4672 }, { 66, 2, 8 },
};
#define NFIELD (sizeof FIELD / sizeof FIELD[0])

static long sys6(long n, long a, long b, long c, long d, long e, long f)
{
    register long x8 __asm__("x8") = n;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    register long x4 __asm__("x4") = e;
    register long x5 __asm__("x5") = f;
    __asm__ volatile("svc #0"
                     : "+r"(x0)
                     : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5)
                     : "memory");
    return x0;
}
#define sys4(n, a, b, c, d) sys6((n), (a), (b), (c), (d), 0, 0)

static int append(char *out, int at, const char *s)
{
    while (*s) out[at++] = *s++;
    return at;
}

static int put_u(char *out, int at, unsigned long v)
{
    char tmp[20];
    int n = 0;
    if (!v) tmp[n++] = '0';
    while (v) { tmp[n++] = (char)('0' + v % 10); v /= 10; }
    while (n) out[at++] = tmp[--n];
    return at;
}

static int put_hex(char *out, int at, unsigned long v)
{
    static const char D[] = "0123456789abcdef";
    char tmp[17];
    int n = 0;
    if (!v) tmp[n++] = '0';
    while (v) { tmp[n++] = D[v & 15]; v >>= 4; }
    at = append(out, at, "0x");
    while (n) out[at++] = tmp[--n];
    return at;
}

static int slurp(const char *path, char *buf, int cap)
{
    long fd = sys4(SYS_openat, AT_FDCWD, (long)path, O_RDONLY, 0);
    int got = 0;
    if (fd < 0) return (int)fd;
    for (;;) {
        long n = sys4(SYS_read, fd, (long)(buf + got), cap - 1 - got, 0);
        if (n <= 0) break;
        got += (int)n;
        if (got >= cap - 1) break;
    }
    sys4(SYS_close, fd, 0, 0, 0);
    buf[got] = 0;
    return got;
}

static unsigned long hex_line(const char **p)
{
    const char *s = *p;
    unsigned long v = 0;
    int any = 0;
    while (*s == ' ' || *s == '\t') s++;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) s += 2;
    for (;;) {
        char c = *s;
        int d;
        if (c >= '0' && c <= '9') d = c - '0';
        else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') d = c - 'A' + 10;
        else break;
        v = v * 16 + (unsigned)d;
        any = 1;
        s++;
    }
    while (*s && *s != '\n') s++;
    if (*s == '\n') s++;
    *p = s;
    return any ? v : 0;
}

static int word_is(const char **p, const char *want)
{
    const char *s = *p, *w = want;
    while (*w && *s == *w) { s++; w++; }
    return *w == 0 && (*s == 0 || *s == '\n' || *s == '\r');
}

/* is this byte inside one of the six fields? */
static int in_field(int i)
{
    unsigned k;
    for (k = 0; k < NFIELD; k++)
        if (i == FIELD[k].at || i == FIELD[k].at + 1)
            return 1;
    return 0;
}

static void clean_dcache(unsigned char *p, unsigned long len)
{
    unsigned long line = 64;                 /* conservative */
    unsigned long a = (unsigned long)p & ~(line - 1);
    unsigned long end = (unsigned long)p + len;
    __asm__ volatile("dsb sy" ::: "memory");
    for (; a < end; a += line)
        __asm__ volatile("dc civac, %0" :: "r"(a) : "memory");
    __asm__ volatile("dsb sy\nisb" ::: "memory");
}

void CreateScriptI(void);
void LoadScriptI(void);
void RunScriptI(void);

static char report[65536];
static char scratch[4096];

static void go(void)
{
    int at = 0;
    long fd;
    unsigned long addr = 0;
    int want_patch = 0, want_restore = 0;
    unsigned k;

    at = append(report, at, "jit_ogpatch\n");

    if (slurp(PARAMS, scratch, sizeof scratch) > 0) {
        const char *p = scratch;
        addr = hex_line(&p);
        if (word_is(&p, "patch")) want_patch = 1;
        else if (word_is(&p, "restore")) want_restore = 1;
    }

    at = append(report, at, "address ");
    at = put_hex(report, at, addr);
    at = append(report, at, want_patch ? "  mode patch\n"
                          : want_restore ? "  mode restore\n"
                          : "  mode check only (no write)\n");

    if (!addr) {
        at = append(report, at, "no address given; nothing done.\n");
        goto out;
    }

    fd = sys4(SYS_openat, AT_FDCWD, (long)"/dev/mem",
              (want_patch || want_restore) ? O_RDWR : O_RDONLY, 0);
    if (fd < 0) {
        at = append(report, at, "open /dev/mem failed, errno -");
        at = put_u(report, at, (unsigned long)(-fd));
        at = append(report, at, "\n");
        goto out;
    }

    {
        unsigned long page = addr & ~(4095UL);
        unsigned long skew = addr - page;
        unsigned long span = (skew + SIGLEN + 4095UL) & ~(4095UL);
        int prot = PROT_READ | ((want_patch || want_restore) ? PROT_WRITE : 0);
        unsigned char *map = (unsigned char *)sys6(SYS_mmap, 0, (long)span, prot,
                                                   MAP_SHARED, fd, (long)page);
        unsigned char *t;
        int bad = 0;

        if (map == (unsigned char *)MAP_FAILED || (long)map < 0) {
            at = append(report, at, "mmap failed, errno -");
            at = put_u(report, at, (unsigned long)(-(long)map));
            at = append(report, at, "\n");
            sys4(SYS_close, fd, 0, 0, 0);
            goto out;
        }
        t = map + skew;

        /* every byte outside the six fields must still match the signature */
        for (k = 0; k < SIGLEN; k++) {
            if (in_field((int)k)) continue;
            if (t[k] != SIG[k]) { bad = 1; break; }
        }
        if (bad) {
            at = append(report, at, "the signature does not match at this "
                                    "address (first difference at +");
            at = put_u(report, at, k);
            at = append(report, at, "). Nothing written.\n");
            sys4(SYS_munmap, (long)map, (long)span, 0, 0);
            sys4(SYS_close, fd, 0, 0, 0);
            goto out;
        }
        at = append(report, at, "signature matches outside the six fields\n");

        at = append(report, at, "field values now:\n");
        for (k = 0; k < NFIELD; k++) {
            unsigned short v = (unsigned short)(t[FIELD[k].at]
                               | (t[FIELD[k].at + 1] << 8));
            at = append(report, at, "  +");
            at = put_u(report, at, FIELD[k].at);
            at = append(report, at, " = ");
            at = put_u(report, at, v);
            at = append(report, at, v == FIELD[k].old ? "  (original)"
                                  : v == FIELD[k].nw ? "  (patched)"
                                  : "  (UNEXPECTED)");
            at = append(report, at, "\n");
            if (v != FIELD[k].old && v != FIELD[k].nw) bad = 1;
        }
        if (bad) {
            at = append(report, at, "a field holds neither the original nor "
                                    "the patched value. Nothing written.\n");
        } else if (want_patch || want_restore) {
            for (k = 0; k < NFIELD; k++) {
                unsigned short v = want_patch ? FIELD[k].nw : FIELD[k].old;
                t[FIELD[k].at] = (unsigned char)(v & 0xff);
                t[FIELD[k].at + 1] = (unsigned char)(v >> 8);
            }
            clean_dcache(t, SIGLEN);
            sys4(SYS_msync, (long)map, (long)span, MS_SYNC, 0);

            at = append(report, at, "written; reading back:\n");
            for (k = 0; k < NFIELD; k++) {
                unsigned short v = (unsigned short)(t[FIELD[k].at]
                                   | (t[FIELD[k].at + 1] << 8));
                unsigned short want = want_patch ? FIELD[k].nw : FIELD[k].old;
                at = append(report, at, "  +");
                at = put_u(report, at, FIELD[k].at);
                at = append(report, at, " = ");
                at = put_u(report, at, v);
                at = append(report, at, v == want ? "  ok\n" : "  DID NOT TAKE\n");
            }
            at = append(report, at,
                        "a power cycle undoes this: only the loaded copy was "
                        "changed, never /cp/cpapp-b.bin.\n");
        }

        sys4(SYS_munmap, (long)map, (long)span, 0, 0);
        sys4(SYS_close, fd, 0, 0, 0);
    }

out:
    fd = sys4(SYS_openat, AT_FDCWD, (long)REPORT, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) {
        sys4(SYS_write, fd, (long)report, at, 0);
        sys4(SYS_close, fd, 0, 0, 0);
    }
}

__attribute__((constructor)) static void on_load(void) { go(); }

void CreateScriptI(void) { }
void LoadScriptI(void) { }
void RunScriptI(void) { }
