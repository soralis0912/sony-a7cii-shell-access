/*
 * A read-only libJit.so: collect what is still unknown about the camera's
 * runtime and write it to /tmp/jiritsu/jit_report.txt, which the host reads
 * back with SET_FILE_PATH + GET_FILE2.
 *
 * It CHANGES NOTHING on the camera. The only write is the report itself, in
 * the same directory the loader already uses. No libc: raw syscalls only, so
 * the camera's glibc version is irrelevant (no DT_NEEDED).
 *
 * What it answers, in order:
 *   - who we are: /proc/self/status (uid/gid), /proc/self/cmdline (which
 *     process dlopened us), uname
 *   - which shells exist: listings of /bin, /sbin, /usr/bin, /usr/sbin
 *   - what is mounted: /proc/mounts, which also settles whether /tmp_wbshd is
 *     tmpfs and what /tmp, /etc and /var really are
 *   - the SSH side: a listing of /etc/ssh and whether /etc/shadow exists
 *     (its SIZE only - the hashes are not copied)
 *   - what is running: every /proc/<pid>/cmdline
 *
 * Build:  aarch64-elf-gcc -shared -fPIC -nostdlib -O1 -o libJit_probe.so jit_probe.c
 */

#define SYS_openat       56
#define SYS_close        57
#define SYS_getdents64   61
#define SYS_read         63
#define SYS_write        64
#define SYS_newfstatat   79
#define SYS_uname       160
#define SYS_getpid      172
#define SYS_getuid      174
#define SYS_geteuid     175

#define AT_FDCWD   (-100)
#define O_RDONLY   0
#define O_WRONLY   01
#define O_CREAT    0100
#define O_TRUNC    01000
#define O_DIRECTORY 040000

#define REPORT "/tmp/jiritsu/jit_report.txt"
#define CAP (48 * 1024)

static char out[CAP];
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

static void emit(const char *s)
{
    while (*s && out_n < CAP - 1)
        out[out_n++] = *s++;
}

static void emit_n(const char *s, long len)
{
    while (len-- > 0 && out_n < CAP - 1)
        out[out_n++] = *s++;
}

static void emit_u(unsigned long v)
{
    char tmp[24];
    int n = 0;
    if (!v) { emit("0"); return; }
    while (v) { tmp[n++] = (char)('0' + (v % 10)); v /= 10; }
    while (n) { if (out_n < CAP - 1) out[out_n++] = tmp[--n]; else break; }
}

/* copy a whole file into the report, truncated to `limit` bytes */
static void cat(const char *path, long limit)
{
    char buf[1024];
    long fd = sys(SYS_openat, AT_FDCWD, (long)path, O_RDONLY, 0);
    long total = 0, n;
    emit("--- ");
    emit(path);
    if (fd < 0) { emit("  (cannot open)\n"); return; }
    emit("\n");
    while (total < limit) {
        n = sys(SYS_read, fd, (long)buf, sizeof(buf), 0);
        if (n <= 0)
            break;
        if (total + n > limit)
            n = limit - total;
        emit_n(buf, n);
        total += n;
    }
    sys(SYS_close, fd, 0, 0, 0);
    if (out_n < CAP - 1 && (out_n == 0 || out[out_n - 1] != '\n'))
        emit("\n");
}

/* one line per directory entry: name and d_type */
static void list_dir(const char *path)
{
    char buf[2048];
    long fd = sys(SYS_openat, AT_FDCWD, (long)path, O_RDONLY | O_DIRECTORY, 0);
    long n;
    emit("--- ");
    emit(path);
    if (fd < 0) { emit("  (cannot open)\n"); return; }
    emit("\n");
    while ((n = sys(SYS_getdents64, fd, (long)buf, sizeof(buf), 0)) > 0) {
        long at = 0;
        while (at < n) {
            unsigned short reclen = *(unsigned short *)(buf + at + 16);
            unsigned char type = *(unsigned char *)(buf + at + 18);
            const char *name = buf + at + 19;
            if (name[0] != '.') {
                emit("  ");
                emit(name);
                emit(type == 4 ? "/" : (type == 10 ? "@" : ""));
                emit("\n");
            }
            if (!reclen)
                break;
            at += reclen;
        }
    }
    sys(SYS_close, fd, 0, 0, 0);
}

/* presence and size only - never the contents */
static void size_of(const char *path)
{
    /* struct stat is 128 bytes on aarch64; st_size is at offset 48 */
    char st[128];
    long r = sys(SYS_newfstatat, AT_FDCWD, (long)path, (long)st, 0);
    emit("  ");
    emit(path);
    if (r < 0) { emit(": absent\n"); return; }
    emit(": present, ");
    emit_u(*(unsigned long *)(st + 48));
    emit(" bytes\n");
}

static int is_digits(const char *s)
{
    if (!*s) return 0;
    while (*s) { if (*s < '0' || *s > '9') return 0; ++s; }
    return 1;
}

/* every /proc/<pid>/cmdline, which is what `ps` would show */
static void process_list(void)
{
    char buf[2048], path[64], cmd[256];
    long fd = sys(SYS_openat, AT_FDCWD, (long)"/proc", O_RDONLY | O_DIRECTORY, 0);
    long n;
    emit("--- processes (/proc/<pid>/cmdline)\n");
    if (fd < 0) { emit("  (cannot open /proc)\n"); return; }
    while ((n = sys(SYS_getdents64, fd, (long)buf, sizeof(buf), 0)) > 0) {
        long at = 0;
        while (at < n) {
            unsigned short reclen = *(unsigned short *)(buf + at + 16);
            const char *name = buf + at + 19;
            if (is_digits(name)) {
                int i = 0, j;
                const char *p = "/proc/";
                while (*p) path[i++] = *p++;
                for (j = 0; name[j] && i < 40; ++j) path[i++] = name[j];
                p = "/cmdline";
                while (*p) path[i++] = *p++;
                path[i] = 0;
                long f2 = sys(SYS_openat, AT_FDCWD, (long)path, O_RDONLY, 0);
                if (f2 >= 0) {
                    long got = sys(SYS_read, f2, (long)cmd, sizeof(cmd) - 1, 0);
                    sys(SYS_close, f2, 0, 0, 0);
                    if (got > 0) {
                        long k;
                        for (k = 0; k < got; ++k)
                            if (cmd[k] == 0) cmd[k] = ' ';
                        cmd[got] = 0;
                        emit("  ");
                        emit(name);
                        emit("  ");
                        emit(cmd);
                        emit("\n");
                    }
                }
            }
            if (!reclen) break;
            at += reclen;
        }
    }
    sys(SYS_close, fd, 0, 0, 0);
}

__attribute__((constructor))
static void jit_probe(void)
{
    char uts[390];
    long fd;

    emit("== jit_probe, read-only\npid=");
    emit_u((unsigned long)sys(SYS_getpid, 0, 0, 0, 0));
    emit(" uid=");
    emit_u((unsigned long)sys(SYS_getuid, 0, 0, 0, 0));
    emit(" euid=");
    emit_u((unsigned long)sys(SYS_geteuid, 0, 0, 0, 0));
    emit("\n");

    if (sys(SYS_uname, (long)uts, 0, 0, 0) == 0) {
        emit("uname: ");
        emit(uts);          /* sysname */
        emit(" ");
        emit(uts + 65 * 2); /* release */
        emit(" ");
        emit(uts + 65 * 3); /* version */
        emit(" ");
        emit(uts + 65 * 4); /* machine */
        emit("\n");
    }

    cat("/proc/self/cmdline", 256);
    cat("/proc/self/status", 1024);
    cat("/proc/mounts", 4096);

    list_dir("/bin");
    list_dir("/sbin");
    list_dir("/usr/bin");
    list_dir("/usr/sbin");
    list_dir("/etc/ssh");

    emit("--- files, presence and size only\n");
    size_of("/etc/shadow");
    size_of("/etc/passwd");
    size_of("/etc/nsswitch.conf");
    size_of("/etc/ssh/sshd_config");
    size_of("/bin/sh");
    size_of("/bin/ash");
    size_of("/bin/busybox");
    size_of("/usr/sbin/sshd");
    size_of("/setting/ulogio.bin");
    size_of("/tmp/jbusy");
    size_of("/tmp/jmode");

    process_list();

    emit("== end\n");

    fd = sys(SYS_openat, AT_FDCWD, (long)REPORT,
             O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0)
        return;
    sys(SYS_write, fd, (long)out, out_n, 0);
    sys(SYS_close, fd, 0, 0, 0);
}

/* kept so the jit_thread path would also accept this library */
void *CreateScriptI(void) { return (void *)1; }
int   LoadScriptI(void *s) { (void)s; return 0; }
int   RunScriptI(void *s)  { (void)s; return 0; }
