/*
 * The smallest libJit.so the camera's loader will accept, plus proof that it ran.
 *
 * IM_JIRITSU::CImJiritsu::jit_thread (libJiritsu.so 2.01, 0xbc74) does:
 *
 *   ramdisk_mount("/tmp/jiritsu/ramdsk_libJit", "size=5M")
 *   sys_file_copy(<the file SET_FILE wrote>, "/tmp/jiritsu/ramdsk_libJit/libJit.so")
 *   handle = dlopen("/tmp/jiritsu/ramdsk_libJit/libJit.so", RTLD_LAZY)
 *   create = dlsym(handle, "CreateScriptI");   obj = create();   // must be non-zero
 *   load   = dlsym(handle, "LoadScriptI");
 *   run    = dlsym(handle, "RunScriptI");
 *
 * CreateScriptI is called with no argument set up (objdump at 0xc0e8: `blr x25`
 * with x0 left over from the preceding log call), and its result is checked
 * against zero, so the prototype is effectively `void *CreateScriptI(void)`.
 * A missing CreateScriptI gives error 20, a missing LoadScriptI 19, a zero
 * return 16.
 *
 * The constructor runs at dlopen time, which is where our code goes. It writes
 * one short file into /tmp/jiritsu/, which can be read back with
 * SET_FILE_PATH + GET_FILE2 - that read-back is the proof that the library was
 * loaded and our code executed inside the service process.
 *
 * Nothing here touches the camera's own files. Keep it that way for the first
 * run: the point is to confirm execution, not to change anything.
 */
#include <stdio.h>
#include <unistd.h>

#define MARKER "/tmp/jiritsu/jit_hello.txt"

__attribute__((constructor))
static void jit_boot(void)
{
    FILE *f = fopen(MARKER, "w");
    if (f == NULL)
        return;
    /* enough to prove which process loaded us and when */
    fprintf(f, "libJit loaded\npid=%d uid=%d euid=%d\n",
            (int)getpid(), (int)getuid(), (int)geteuid());
    fclose(f);
}

/* the three symbols the loader resolves; CreateScriptI must not return 0 */
void *CreateScriptI(void) { return (void *)1; }
int   LoadScriptI(void *script) { (void)script; return 0; }
int   RunScriptI(void *script)  { (void)script; return 0; }
