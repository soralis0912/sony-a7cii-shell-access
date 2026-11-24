/*
 * libJit_ogscan.so - find the sensor readout-mode table in the running
 * camera's memory. READ ONLY: it opens /dev/mem O_RDONLY and writes nothing
 * anywhere but its own report file.
 *
 * The open-gate work located the table in the coprocessor image
 * p8 cpapp-b.bin at file offset 0xdd832e, where a 76-byte window covering the
 * two 7008x3942 records is unique in the whole 18 MB image. That window is
 * the signature below. Finding it in RAM gives the physical address the
 * records live at while the camera is running, which is what an on-memory
 * test needs and what no amount of static analysis can supply.
 *
 * Parameters come from /tmp/jiritsu/DIAC.csv, one per line, hex, no 0x:
 *     line 1   physical start address
 *     line 2   length to scan
 * With no parameters it only dumps /proc/iomem and /proc/cmdline, which is
 * the right first run - that is where the coprocessor's reserved region is
 * named, and guessing a range before reading them is pointless.
 *
 * Build:  aarch64-elf-gcc -shared -fPIC -nostdlib -O1 -o libJit_ogscan.so jit_ogscan.c
 */

#define SYS_openat   56
#define SYS_read     63
#define SYS_write    64
#define SYS_close    57
#define SYS_mmap    222
#define SYS_munmap  215

#define AT_FDCWD     (-100)
#define O_RDONLY     00
#define O_WRONLY     01
#define O_CREAT      0100
#define O_TRUNC      01000
#define PROT_READ    0x1
#define MAP_SHARED   0x01
#define MAP_FAILED   ((void *)-1)

#define REPORT  "/tmp/jiritsu/jit_report.txt"
#define PARAMS  "/tmp/jiritsu/DIAC.csv"

/* 76 bytes from cpapp-b.bin:0xdd832e - unique in the image */
static const unsigned char SIG[] = { 0x10,0x00,0x0c,0x00,0x0c,0x00,0x60,0x1b,0x0c,0x00,0x04,0x00,0x00,0x00,0x00,0x00,0x22,0x00,0x18,0x00,0x02,0x00,0x08,0x00,0x66,0x0f,0x08,0x00,0x02,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x10,0x00,0x0c,0x00,0x0c,0x00,0x60,0x1b,0x0c,0x00,0x04,0x00,0x00,0x00,0x00,0x00,0x22,0x00,0x18,0x00,0x02,0x00,0x08,0x00,0x66,0x0f,0x08,0x00,0x02,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00 };
#define SIGLEN (sizeof SIG)

/* window size for each mmap of /dev/mem, with an overlap so a signature
 * straddling a boundary is still found */
#define WIN   (8UL << 20)
#define OVER  4096UL

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

static int put_u(char *out, int at, unsigned long v)
{
    char tmp[20];
    int n = 0;
    if (!v) tmp[n++] = '0';
    while (v) { tmp[n++] = (char)('0' + v % 10); v /= 10; }
    while (n) out[at++] = tmp[--n];
    return at;
}

/* read a whole small file; returns length or negative */
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

/* parse one hex number starting at *p, advance past the line */
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

void CreateScriptI(void);
void LoadScriptI(void);
void RunScriptI(void);

static char report[262144];
static char scratch[65536];

static void scan(void)
{
    int at = 0;
    long fd;
    unsigned long start = 0, len = 0;
    int n;

    at = append(report, at, "jit_ogscan: read-only search for the sensor table\n");
    at = append(report, at, "signature length ");
    at = put_u(report, at, SIGLEN);
    at = append(report, at, " bytes, from cpapp-b.bin:0xdd832e\n\n");

    n = slurp(PARAMS, scratch, sizeof scratch);
    if (n > 0) {
        const char *p = scratch;
        start = hex_line(&p);
        len = hex_line(&p);
    }

    at = append(report, at, "=== /proc/cmdline\n");
    if (slurp("/proc/cmdline", scratch, sizeof scratch) > 0)
        at = append(report, at, scratch);
    at = append(report, at, "\n=== /proc/iomem\n");
    if (slurp("/proc/iomem", scratch, sizeof scratch) > 0)
        at = append(report, at, scratch);

    if (!start || !len) {
        at = append(report, at,
                    "\nno range given in DIAC.csv, so nothing was scanned.\n"
                    "Pick one from the two dumps above and run again with\n"
                    "line 1 = physical start, line 2 = length, both hex.\n");
    } else {
        unsigned long off = start & ~(4095UL);
        unsigned long endp = start + len;
        int hits = 0;

        at = append(report, at, "\n=== scanning ");
        at = put_hex(report, at, start);
        at = append(report, at, " + ");
        at = put_hex(report, at, len);
        at = append(report, at, "\n");

        fd = sys4(SYS_openat, AT_FDCWD, (long)"/dev/mem", O_RDONLY, 0);
        if (fd < 0) {
            at = append(report, at, "open /dev/mem failed, errno -");
            at = put_u(report, at, (unsigned long)(-fd));
            at = append(report, at, "\n");
        } else {
            while (off < endp) {
                unsigned long want = endp - off;
                unsigned char *map;
                if (want > WIN) want = WIN;
                map = (unsigned char *)sys6(SYS_mmap, 0, (long)want, PROT_READ,
                                            MAP_SHARED, fd, (long)off);
                if (map == (unsigned char *)MAP_FAILED || (long)map < 0) {
                    at = append(report, at, "  mmap failed at ");
                    at = put_hex(report, at, off);
                    at = append(report, at, "\n");
                    if (want <= OVER) break;
                    off += WIN - OVER;
                    continue;
                }
                {
                    unsigned long i, limit = want >= SIGLEN ? want - SIGLEN : 0;
                    for (i = 0; i < limit; i++) {
                        unsigned long j;
                        if (map[i] != SIG[0]) continue;
                        for (j = 1; j < SIGLEN; j++)
                            if (map[i + j] != SIG[j]) break;
                        if (j != SIGLEN) continue;
                        at = append(report, at, "  FOUND at physical ");
                        at = put_hex(report, at, off + i);
                        at = append(report, at, "\n");
                        hits++;
                        if (hits >= 16) break;
                    }
                }
                sys4(SYS_munmap, (long)map, (long)want, 0, 0);
                if (hits >= 16) break;
                if (want <= OVER) break;
                off += want - OVER;
            }
            sys4(SYS_close, fd, 0, 0, 0);
        }
        at = append(report, at, "hits: ");
        at = put_u(report, at, (unsigned long)hits);
        at = append(report, at, "\n");
    }

    fd = sys4(SYS_openat, AT_FDCWD, (long)REPORT, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) {
        sys4(SYS_write, fd, (long)report, at, 0);
        sys4(SYS_close, fd, 0, 0, 0);
    }
}

__attribute__((constructor)) static void on_load(void) { scan(); }

void CreateScriptI(void) { }
void LoadScriptI(void) { }
void RunScriptI(void) { }
