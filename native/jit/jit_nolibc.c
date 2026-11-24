/*
 * libJit.so without libc: the same three exports and the same proof-of-life
 * marker, written with raw Linux syscalls.
 *
 * Why this variant exists: the camera's root filesystem is glibc 2.25, and a
 * cross toolchain built against a newer glibc emits references to symbol
 * versions it cannot resolve. Using no libc at all removes the question -
 * the library needs nothing from the camera beyond the kernel.
 *
 * Build it with the bare-metal toolchain (Homebrew core, no third-party tap):
 *     aarch64-elf-gcc -shared -fPIC -nostdlib -O1 -o libJit.so jit_nolibc.c
 *
 * jit.c is the libc version, which reads better but needs a glibc cross
 * toolchain. Both are equivalent in what they prove.
 */

/* AArch64 Linux syscall numbers */
#define SYS_openat   56
#define SYS_write    64
#define SYS_close    57
#define SYS_getpid   172
#define SYS_getuid   174
#define SYS_geteuid  175

#define AT_FDCWD     (-100)
#define O_WRONLY     01
#define O_CREAT      0100
#define O_TRUNC      01000

static long sys(long n, long a, long b, long c, long d)
{
    register long x8 __asm__("x8") = n;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    __asm__ volatile("svc #0"
                     : "+r"(x0)
                     : "r"(x8), "r"(x1), "r"(x2), "r"(x3)
                     : "memory");
    return x0;
}

static int put_u(char *out, unsigned long v)
{
    char tmp[20];
    int n = 0, i = 0;
    if (v == 0)
        tmp[n++] = '0';
    while (v) { tmp[n++] = (char)('0' + (v % 10)); v /= 10; }
    while (n) out[i++] = tmp[--n];
    return i;
}

static int append(char *out, int at, const char *s)
{
    while (*s) out[at++] = *s++;
    return at;
}

__attribute__((constructor))
static void jit_boot(void)
{
    static const char path[] = "/tmp/jiritsu/jit_hello.txt";
    char buf[128];
    int n = 0;
    long fd;

    n = append(buf, n, "libJit loaded\npid=");
    n += put_u(buf + n, (unsigned long)sys(SYS_getpid, 0, 0, 0, 0));
    n = append(buf, n, " uid=");
    n += put_u(buf + n, (unsigned long)sys(SYS_getuid, 0, 0, 0, 0));
    n = append(buf, n, " euid=");
    n += put_u(buf + n, (unsigned long)sys(SYS_geteuid, 0, 0, 0, 0));
    buf[n++] = '\n';

    /* openat takes the mode in the fourth argument; pass it explicitly rather
       than leaving x3 to chance, or O_CREAT gets whatever was in the register */
    fd = sys(SYS_openat, AT_FDCWD, (long)path,
             O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0)
        return;
    sys(SYS_write, fd, (long)buf, n, 0);
    sys(SYS_close, fd, 0, 0, 0);
}

/* the three symbols jit_thread resolves; CreateScriptI must not return 0 */
void *CreateScriptI(void) { return (void *)1; }
int   LoadScriptI(void *script) { (void)script; return 0; }
int   RunScriptI(void *script)  { (void)script; return 0; }
