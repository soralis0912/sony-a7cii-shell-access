/*
 * Generate a 33x33x33 .cube LUT on the camera itself.
 *
 * Transferring a 970 KB text file over the Jiritsu channel is awkward, and the
 * camera's shell has no awk, so the LUT is computed here instead. All values
 * land exactly on six decimals: an index n in 0..32 is n * 31250 / 1000000, so
 * nothing is rounded.
 *
 * Parameters come from /tmp/jiritsu/DIAC.csv, which jit_load.py --run writes:
 *
 *     line 1: the output path, e.g. /usr/data/lut/test.cube
 *     line 2: a mode - "identity" or "swap" (R and B exchanged) or
 *             "green" (green at 20%, which is unmistakable on screen)
 *
 * Before writing, if the output already exists and <path>.orig does not, the
 * original is copied to <path>.orig. So overwriting a stock LUT keeps a copy
 * next to it.
 *
 * The camera's own files are this format (LUT_3D_SIZE 33, 35,937 data lines,
 * "%.6f %.6f %.6f"), and r709.cube has no comment header while S709.cube has
 * two comment lines; both are accepted by whatever reads them, so this writes
 * one comment line.
 *
 * Build: aarch64-elf-gcc -shared -fPIC -nostdlib -O1 -o libJit_lut.so jit_lut.c
 */

#define SYS_openat 56
#define SYS_close  57
#define SYS_read   63
#define SYS_write  64
#define SYS_newfstatat 79

#define AT_FDCWD (-100)
#define O_RDONLY 0
#define O_WRONLY 01
#define O_CREAT  0100
#define O_TRUNC  01000

#define CMDFILE "/tmp/jiritsu/DIAC.csv"
#define REPORT  "/tmp/jiritsu/jit_report.txt"
#define SIZE 33
#define BUF  (64 * 1024)

static char params[512];
static char outbuf[BUF];
static int  outn;
static char path[256];
static char orig[256 + 8];
static char mode[32];
static char report[2048];
static int  repn;

static long sys(long n, long a, long b, long c, long d)
{
    register long x8 __asm__("x8") = n;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    __asm__ volatile("svc #0" : "+r"(x0)
                     : "r"(x8), "r"(x1), "r"(x2), "r"(x3) : "memory");
    return x0;
}

static long slen(const char *s) { const char *p = s; while (*p) ++p; return p - s; }
static void emits(const char *s);

static void rep(const char *s) { while (*s && repn < (int)sizeof(report) - 1) report[repn++] = *s++; }

static void rep_i(long v)
{
    char t[24]; int n = 0;
    if (v < 0) { rep("-"); v = -v; }
    if (!v) { rep("0"); return; }
    while (v) { t[n++] = (char)('0' + v % 10); v /= 10; }
    while (n && repn < (int)sizeof(report) - 1) report[repn++] = t[--n];
}

static long fd_out = -1;

static void flush(void)
{
    if (outn > 0 && fd_out >= 0)
        sys(SYS_write, fd_out, (long)outbuf, outn, 0);
    outn = 0;
}

static void emit(const char *s, int n)
{
    int i;
    if (outn + n > BUF)
        flush();
    for (i = 0; i < n; ++i)
        outbuf[outn++] = s[i];
}

static void emits(const char *s) { emit(s, (int)slen(s)); }

/* v is in millionths, 0..1000000 -> "d.dddddd" */
static void emit_val(long v)
{
    char t[10];
    long frac = v % 1000000;
    int i;
    t[0] = (char)('0' + v / 1000000);
    t[1] = '.';
    for (i = 7; i >= 2; --i) { t[i] = (char)('0' + frac % 10); frac /= 10; }
    emit(t, 8);
}

static int streq(const char *a, const char *b)
{
    while (*a && *a == *b) { ++a; ++b; }
    return *a == *b;
}

static int exists(const char *p)
{
    char st[128];
    return sys(SYS_newfstatat, AT_FDCWD, (long)p, (long)st, 0) == 0;
}

/* copy src to dst, 64 KB at a time; returns bytes copied or -1 */
static long copy(const char *src, const char *dst)
{
    static char chunk[16 * 1024];
    long in = sys(SYS_openat, AT_FDCWD, (long)src, O_RDONLY, 0);
    long out, n, total = 0;
    if (in < 0) return -1;
    out = sys(SYS_openat, AT_FDCWD, (long)dst, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (out < 0) { sys(SYS_close, in, 0, 0, 0); return -1; }
    while ((n = sys(SYS_read, in, (long)chunk, sizeof(chunk), 0)) > 0) {
        sys(SYS_write, out, (long)chunk, n, 0);
        total += n;
    }
    sys(SYS_close, in, 0, 0, 0);
    sys(SYS_close, out, 0, 0, 0);
    return total;
}

__attribute__((constructor))
static void jit_lut(void)
{
    long in, n, i, j, k;
    int p = 0, q = 0;

    in = sys(SYS_openat, AT_FDCWD, (long)CMDFILE, O_RDONLY, 0);
    if (in >= 0) {
        n = sys(SYS_read, in, (long)params, sizeof(params) - 1, 0);
        sys(SYS_close, in, 0, 0, 0);
        if (n > 0) params[n] = 0;
    }
    /* line 1 -> path, line 2 -> mode */
    while (params[p] && params[p] != '\n' && q < (int)sizeof(path) - 1)
        path[q++] = params[p++];
    path[q] = 0;
    if (params[p] == '\n') ++p;
    q = 0;
    while (params[p] && params[p] != '\n' && q < (int)sizeof(mode) - 1)
        mode[q++] = params[p++];
    mode[q] = 0;

    rep("== jit_lut\npath: ");
    rep(path[0] ? path : "(none given)");
    rep("\nmode: ");
    rep(mode[0] ? mode : "identity");
    rep("\n");

    if (!path[0]) { rep("no output path on line 1 of DIAC.csv\n== end\n"); goto save; }

    /* keep a copy of whatever is there */
    for (q = 0; path[q]; ++q) orig[q] = path[q];
    orig[q] = 0;
    { const char *s = ".orig"; int r = 0; while (s[r]) orig[q++] = s[r++]; orig[q] = 0; }
    if (exists(path)) {
        if (exists(orig)) {
            rep("original already saved at ");
            rep(orig);
            rep("\n");
        } else {
            long c = copy(path, orig);
            rep("saved the original to ");
            rep(orig);
            rep(": ");
            rep_i(c);
            rep(" bytes\n");
            if (c < 0) { rep("could not save it - refusing to overwrite\n== end\n"); goto save; }
        }
    } else {
        rep("no file there yet; writing a new one\n");
    }

    fd_out = sys(SYS_openat, AT_FDCWD, (long)path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd_out < 0) { rep("cannot open the output\n== end\n"); goto save; }

    emits("# generated on the camera\nLUT_3D_SIZE 33\n");
    /* .cube order: R varies fastest, then G, then B */
    for (k = 0; k < SIZE; ++k)
        for (j = 0; j < SIZE; ++j)
            for (i = 0; i < SIZE; ++i) {
                long r = i * 31250, g = j * 31250, b = k * 31250;
                if (streq(mode, "swap")) { long t = r; r = b; b = t; }
                else if (streq(mode, "green")) { g = g / 5; }
                emit_val(r); emit(" ", 1);
                emit_val(g); emit(" ", 1);
                emit_val(b); emit("\n", 1);
            }
    flush();
    sys(SYS_close, fd_out, 0, 0, 0);
    fd_out = -1;

    rep("wrote ");
    rep_i((long)SIZE * SIZE * SIZE);
    rep(" data lines\n== end\n");

save:
    {
        long f = sys(SYS_openat, AT_FDCWD, (long)REPORT,
                     O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (f >= 0) { sys(SYS_write, f, (long)report, repn, 0); sys(SYS_close, f, 0, 0, 0); }
    }
}

void *CreateScriptI(void) { return (void *)1; }
int   LoadScriptI(void *s) { (void)s; return 0; }
int   RunScriptI(void *s)  { (void)s; return 0; }
