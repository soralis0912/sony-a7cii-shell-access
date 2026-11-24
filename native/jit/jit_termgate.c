/*
 * Clear the one byte that refuses TERM_MODE, from inside the process.
 *
 * Which byte, and why this one:
 *
 *   libsencore.so holds the adjust-command table - 0x48-byte records of
 *   [u32 subsystem id][u16 category][u8 command][u8 flags][name]. TERM_MODE is
 *   category 0x0601, command 0x1f, flags 0x80, and its flags byte is at file
 *   offset 0x27833 (VA 0x27833: in this library .rodata's address equals its
 *   file offset). The A7 IV project's published libsencore patch is the same
 *   field in their build - 0x26e13, 0x80 -> 0x00 - so clearing it is a
 *   demonstrated fix.
 *
 *   NOT terminal_change_function_is_disabled (VA 0x6d9a0, .data). That one is
 *   set from the service level, and this camera is level A, so it already
 *   reads 0. The read-only survey confirmed the gate it guards is open. This
 *   library reports its value too, so the distinction stays checkable.
 *
 * The page is .rodata, mapped read-only, so it needs mprotect. The mapping is
 * MAP_PRIVATE and file-backed, so the write is copy-on-write: the partition is
 * not touched and a power cycle undoes everything.
 *
 * It refuses to write unless the eight bytes at base+0x2782c are exactly the
 * TERM_MODE record's header. Everything it does goes into the report.
 *
 * Build: aarch64-elf-gcc -shared -fPIC -nostdlib -O1 -o libJit_termgate.so jit_termgate.c
 */

#define SYS_openat    56
#define SYS_close     57
#define SYS_read      63
#define SYS_write     64
#define SYS_mprotect 226

#define AT_FDCWD  (-100)
#define O_RDONLY  0
#define O_WRONLY  01
#define O_CREAT   0100
#define O_TRUNC   01000
#define PROT_READ  1
#define PROT_WRITE 2

#define REPORT "/tmp/jiritsu/jit_report.txt"
#define LIB    "libsencore.so"

/* offsets inside libsencore.so 2.01 (sha256 3362d4b6...79e7) */
#define REC_OFF   0x2782c      /* the TERM_MODE record */
#define FLAG_OFF  0x27833      /* its flags byte */
#define GATE_VA   0x6d9a0      /* terminal_change_function_is_disabled, .data */
static const unsigned char EXPECT[8] = {0x5f, 0x02, 0x3d, 0x00, 0x01, 0x06, 0x1f, 0x80};

static char maps[256 * 1024];
static char out[8 * 1024];
static int out_n;

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

static void emit(const char *s) { while (*s && out_n < (int)sizeof(out) - 1) out[out_n++] = *s++; }

static void emit_hex(unsigned long v, int digits)
{
    static const char d[] = "0123456789abcdef";
    int i;
    emit("0x");
    for (i = digits - 1; i >= 0; --i)
        if (out_n < (int)sizeof(out) - 1)
            out[out_n++] = d[(v >> (4 * i)) & 0xf];
}

static int same(const char *a, const char *b, int n)
{
    while (n--) { if (*a++ != *b++) return 0; }
    return 1;
}

/* the load base of the mapping of LIB whose file offset is 0 */
static unsigned long find_base(void)
{
    long fd = sys(SYS_openat, AT_FDCWD, (long)"/proc/self/maps", O_RDONLY, 0);
    long n, total = 0;
    int i = 0;
    if (fd < 0)
        return 0;
    while (total < (long)sizeof(maps) - 1) {
        n = sys(SYS_read, fd, (long)(maps + total), sizeof(maps) - 1 - total, 0);
        if (n <= 0) break;
        total += n;
    }
    sys(SYS_close, fd, 0, 0, 0);
    maps[total] = 0;

    while (i < total) {
        int start = i, j;
        unsigned long base = 0, offset = 0;
        while (i < total && maps[i] != '\n') ++i;
        maps[i] = 0;                       /* one line at a time */
        /* "<base>-<end> rwxp <offset> dev inode path" */
        for (j = start; maps[j] && maps[j] != '-'; ++j) {
            char c = maps[j];
            base = base * 16 + (unsigned)(c <= '9' ? c - '0' : (c | 32) - 'a' + 10);
        }
        while (maps[j] && maps[j] != ' ') ++j;     /* skip -end */
        while (maps[j] == ' ') ++j;
        while (maps[j] && maps[j] != ' ') ++j;     /* skip perms */
        while (maps[j] == ' ') ++j;
        for (; maps[j] && maps[j] != ' '; ++j) {
            char c = maps[j];
            offset = offset * 16 + (unsigned)(c <= '9' ? c - '0' : (c | 32) - 'a' + 10);
        }
        /* does the line end with LIB ? */
        {
            int len = 0, k, m = 0;
            while (maps[start + len]) ++len;
            while (LIB[m]) ++m;
            k = start + len - m;
            if (k > start && offset == 0 && same(maps + k, LIB, m))
                return base;
        }
        ++i;
    }
    return 0;
}

__attribute__((constructor))
static void jit_termgate(void)
{
    unsigned long base, page;
    unsigned char *rec, *flag, *gate;
    long fd, r;
    int k;

    emit("== jit_termgate\n");
    base = find_base();
    emit("libsencore.so base: ");
    emit_hex(base, 12);
    emit("\n");
    if (!base) { emit("not mapped - nothing done\n"); goto save; }

    rec  = (unsigned char *)(base + REC_OFF);
    flag = (unsigned char *)(base + FLAG_OFF);
    gate = (unsigned char *)(base + GATE_VA);

    emit("record at +0x2782c: ");
    for (k = 0; k < 8; ++k) { emit_hex(rec[k], 2); emit(" "); }
    emit("\n");
    emit("terminal_change_function_is_disabled (+0x6d9a0): ");
    emit_hex(*gate, 2);
    emit(*gate ? "  (set - the level is not A)\n" : "  (clear - level A, as expected)\n");

    for (k = 0; k < 8; ++k)
        if (rec[k] != EXPECT[k]) {
            emit("signature mismatch - refusing to write\n");
            goto save;
        }
    emit("signature ok (category 0x0601, command 0x1f, flags 0x80)\n");

    page = (unsigned long)flag & ~0xfffUL;
    r = sys(SYS_mprotect, (long)page, 0x1000, PROT_READ | PROT_WRITE, 0);
    emit("mprotect rw: ");
    emit_hex((unsigned long)r, 2);
    emit("\n");
    if (r != 0) { emit("could not make the page writable - nothing changed\n"); goto save; }

    *flag = 0x00;
    emit("flags byte now: ");
    emit_hex(*flag, 2);
    emit("\n");

    r = sys(SYS_mprotect, (long)page, 0x1000, PROT_READ, 0);
    emit("mprotect back to ro: ");
    emit_hex((unsigned long)r, 2);
    emit("\n");
    emit("TERM_MODE should now be accepted. Nothing was written to flash:\n");
    emit("the mapping is private and file-backed, so a power cycle undoes it.\n");

save:
    emit("== end\n");
    fd = sys(SYS_openat, AT_FDCWD, (long)REPORT, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return;
    sys(SYS_write, fd, (long)out, out_n, 0);
    sys(SYS_close, fd, 0, 0, 0);
}

void *CreateScriptI(void) { return (void *)1; }
int   LoadScriptI(void *s) { (void)s; return 0; }
int   RunScriptI(void *s)  { (void)s; return 0; }
