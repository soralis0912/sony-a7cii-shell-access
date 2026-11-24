/*
 * Run shell commands on the camera, using the Jiritsu file channel as the
 * transport. This replaces the USB terminal, which is not needed: our code
 * already runs as root inside im.elf.
 *
 * How it works:
 *
 *   The host writes the command text to /tmp/jiritsu/DIAC.csv (SET_FILE index
 *   1), then writes this library to /tmp/jiritsu/libJit.so (index 2). Writing
 *   index 2 makes adj_cmd_set_file dlopen it, which runs this constructor. It
 *   reads DIAC.csv, runs it with /bin/sh -c, and sends stdout and stderr to
 *   /tmp/jiritsu/jit_report.txt, which the host reads back with
 *   SET_FILE_PATH + GET_FILE2.
 *
 *   So: two writes per batch, one read back. One round trip per command batch.
 *
 * No libc: clone/execve/wait4/dup3 by syscall. /bin/sh exists on the camera
 * (423,000 bytes, busybox).
 *
 * This runs whatever it is given, as root. The commands come from the file the
 * host just wrote - nothing else is consulted.
 *
 * Build: aarch64-elf-gcc -shared -fPIC -nostdlib -O1 -o libJit_sh.so jit_sh.c
 */

#define SYS_openat     56
#define SYS_close      57
#define SYS_read       63
#define SYS_write      64
#define SYS_dup3       24
#define SYS_clone     220
#define SYS_execve    221
#define SYS_wait4     260
#define SYS_exit_group 94

#define AT_FDCWD (-100)
#define O_RDONLY 0
#define O_WRONLY 01
#define O_CREAT  0100
#define O_TRUNC  01000
#define SIGCHLD  17

#define CMDFILE "/tmp/jiritsu/DIAC.csv"
#define REPORT  "/tmp/jiritsu/jit_report.txt"
#define CAP 8192

static char cmd[CAP];

static long sys5(long n, long a, long b, long c, long d, long e)
{
    register long x8 __asm__("x8") = n;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    register long x4 __asm__("x4") = e;
    __asm__ volatile("svc #0" : "+r"(x0)
                     : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4) : "memory");
    return x0;
}
#define sys(n, a, b, c, d) sys5((n), (a), (b), (c), (d), 0)

static long slen(const char *s) { const char *p = s; while (*p) ++p; return p - s; }
static void put(long fd, const char *s) { sys(SYS_write, fd, (long)s, slen(s), 0); }

static void put_i(long fd, long v)
{
    char tmp[24], out[24];
    int n = 0, i = 0;
    if (v < 0) { out[i++] = '-'; v = -v; }
    if (!v) tmp[n++] = '0';
    while (v) { tmp[n++] = (char)('0' + (v % 10)); v /= 10; }
    while (n) out[i++] = tmp[--n];
    sys(SYS_write, fd, (long)out, i, 0);
}

__attribute__((constructor))
static void jit_sh(void)
{
    static char *argv[4];
    static char *envp[2];
    static char sh[] = "/bin/sh";
    static char dash_c[] = "-c";
    static char path_env[] = "PATH=/bin:/sbin:/usr/bin:/usr/sbin";
    long in, out, got, pid, status = 0;

    out = sys(SYS_openat, AT_FDCWD, (long)REPORT, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (out < 0)
        return;

    in = sys(SYS_openat, AT_FDCWD, (long)CMDFILE, O_RDONLY, 0);
    if (in < 0) {
        put(out, "== jit_sh\nno command file at " CMDFILE "\n== end\n");
        sys(SYS_close, out, 0, 0, 0);
        return;
    }
    got = sys(SYS_read, in, (long)cmd, CAP - 1, 0);
    sys(SYS_close, in, 0, 0, 0);
    if (got < 0)
        got = 0;
    cmd[got] = 0;

    put(out, "== jit_sh\n--- command\n");
    sys(SYS_write, out, (long)cmd, got, 0);
    put(out, "\n--- output\n");

    argv[0] = sh;
    argv[1] = dash_c;
    argv[2] = cmd;
    argv[3] = 0;
    envp[0] = path_env;
    envp[1] = 0;

    pid = sys5(SYS_clone, SIGCHLD, 0, 0, 0, 0);
    if (pid == 0) {
        sys(SYS_dup3, out, 1, 0, 0);
        sys(SYS_dup3, out, 2, 0, 0);
        sys(SYS_execve, (long)sh, (long)argv, (long)envp, 0);
        put(out, "(execve failed)\n");
        sys(SYS_exit_group, 127, 0, 0, 0);
    }
    if (pid < 0) {
        put(out, "(clone failed: ");
        put_i(out, pid);
        put(out, ")\n== end\n");
        sys(SYS_close, out, 0, 0, 0);
        return;
    }
    sys(SYS_wait4, pid, (long)&status, 0, 0);
    put(out, "--- exit status ");
    put_i(out, (status >> 8) & 0xff);
    put(out, " (raw ");
    put_i(out, status);
    put(out, ")\n== end\n");
    sys(SYS_close, out, 0, 0, 0);
}

void *CreateScriptI(void) { return (void *)1; }
int   LoadScriptI(void *s) { (void)s; return 0; }
int   RunScriptI(void *s)  { (void)s; return 0; }
