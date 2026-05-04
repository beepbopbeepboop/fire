/* compiler_main.c — CLI entry point for the self-hosting Mojo compiler.
 *
 * This file owns ALL OS interface: argc/argv, file I/O, gcc invocation.
 * The Mojo-compiled logic (mojo_main.mojo → C) provides these four symbols:
 *
 *   MojoStr *mojo_gimple(MojoStr *src)   — run full compilation pipeline
 *   MojoStr *mojo_pyir(MojoStr *src)     — Python IR (intermediate)
 *   void     mojo_tokens(MojoStr *src)   — print token stream to stdout
 *   void     mojo_ast(MojoStr *src)      — print AST to stdout
 *
 * Build (stage1):
 *   build/mojo --dump-gimple mojo/mojo_main.mojo > build/mojo_logic.c
 *   gcc -fgimple -I runtime -o stage1/mojo build/mojo_logic.c runtime/compiler_main.c runtime/mojo_runtime.c
 *
 * Build (stage2):
 *   stage1/mojo --dump-gimple mojo/mojo_main.mojo > build/mojo_logic2.c
 *   gcc -fgimple -I runtime -o stage2/mojo build/mojo_logic2.c runtime/compiler_main.c runtime/mojo_runtime.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include "mojo_runtime.h"

#define VERSION "0.1.0"

/* ── Mojo-compiled symbols ───────────────────────────────────────────────
 * Defined in the C generated from mojo/mojo_main.mojo.                   */
extern MojoStr *mojo_gimple(MojoStr *src);
extern MojoStr *mojo_pyir(MojoStr *src);
extern void     mojo_tokens(MojoStr *src);
extern void     mojo_ast(MojoStr *src);

/* ── Helpers ─────────────────────────────────────────────────────────────*/

static char *read_file(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "mojo: cannot open '%s'\n", path);
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    rewind(f);
    char *buf = malloc(len + 1);
    if (!buf) { fclose(f); return NULL; }
    fread(buf, 1, len, f);
    buf[len] = '\0';
    fclose(f);
    return buf;
}

static int file_exists(const char *path)
{
    struct stat st;
    return stat(path, &st) == 0;
}

static const char *find_cc(void)
{
    if (file_exists("/opt/local/bin/gcc-mp-15")) return "/opt/local/bin/gcc-mp-15";
    return "gcc";
}

/* Compile a GIMPLE C string to an ELF.  Returns process exit code. */
static int compile_gimple_to_elf(const char *gimple_src,
                                  const char *out_path,
                                  const char *runtime_dir)
{
    char tmppath[256];
    snprintf(tmppath, sizeof(tmppath), "/tmp/mojo_%d.c", (int)getpid());

    FILE *f = fopen(tmppath, "w");
    if (!f) return 1;
    fputs(gimple_src, f);
    fclose(f);

    char cmd[4096];
    /* Link mojo_logic.c + mojo_runtime.c in one shot.
     * The Mojo-compiled C is already in tmppath; runtime is separate. */
    snprintf(cmd, sizeof(cmd),
             "%s -fgimple -I%s -o %s %s %s/mojo_runtime.c 2>&1",
             find_cc(), runtime_dir, out_path, tmppath, runtime_dir);

    int rc = system(cmd);
    unlink(tmppath);
    return WEXITSTATUS(rc);
}

static void print_help(void)
{
    printf("mojo %s - Mojo language compiler (self-hosting)\n\n", VERSION);
    printf("USAGE:\n");
    printf("    mojo [OPTIONS] [COMMAND] [ARGS]\n\n");
    printf("COMMANDS:\n");
    printf("    run <file.mojo>               Run a Mojo file\n");
    printf("    build <file.mojo> -o <out>    Build to ELF executable\n");
    printf("    <file.mojo>                   Shorthand for 'mojo run'\n\n");
    printf("OPTIONS:\n");
    printf("    -h, --help                    Show this help\n");
    printf("    -v, --version                 Show version\n");
    printf("    -o <file>                     Output file (build)\n");
    printf("    --dump-tokens <file>          Print token stream\n");
    printf("    --dump-ast <file>             Print AST\n");
    printf("    --dump-c <file>               Print Python IR\n");
    printf("    --dump-gimple <file>          Print GIMPLE C\n");
    printf("    --dump-all <file>             Print all representations\n");
}

/* ── Subcommands ─────────────────────────────────────────────────────────*/

static void do_dump(const char *flag, const char *path)
{
    char *raw = read_file(path);
    if (!raw) exit(1);
    MojoStr *src = mojo_str_new(raw);
    free(raw);

    int all = strcmp(flag, "--dump-all") == 0;

    if (all || strcmp(flag, "--dump-tokens") == 0) {
        if (all) printf("=== TOKENS ===\n");
        mojo_tokens(src);
        if (all) printf("\n");
    }
    if (all || strcmp(flag, "--dump-ast") == 0) {
        if (all) printf("=== AST ===\n");
        mojo_ast(src);
        if (all) printf("\n");
    }
    if (all || strcmp(flag, "--dump-c") == 0) {
        if (all) printf("=== C ===\n");
        MojoStr *out = mojo_pyir(src);
        printf("%s\n", mojo_str_data(out));
        if (all) printf("\n");
    }
    if (all || strcmp(flag, "--dump-gimple") == 0) {
        if (all) printf("=== GIMPLE ===\n");
        MojoStr *out = mojo_gimple(src);
        printf("%s\n", mojo_str_data(out));
    }
}

static void do_build(int argc, char **argv, const char *runtime_dir)
{
    const char *input = NULL, *output = NULL;
    for (int i = 0; i < argc; i++) {
        if (!strcmp(argv[i], "-o") && i+1 < argc) output = argv[++i];
        else if (strstr(argv[i], ".mojo"))         input  = argv[i];
    }
    if (!input)  { fprintf(stderr, "mojo build: no input file\n");  exit(1); }
    if (!output) { fprintf(stderr, "mojo build: -o required\n");    exit(1); }

    char *raw = read_file(input);
    if (!raw) exit(1);
    MojoStr *src    = mojo_str_new(raw);  free(raw);
    MojoStr *gimple = mojo_gimple(src);

    int rc = compile_gimple_to_elf(mojo_str_data(gimple), output, runtime_dir);
    if (rc == 0) printf("Built %s\n", output);
    else { fprintf(stderr, "mojo build: compilation failed (cc exit %d)\n", rc); exit(rc); }
}

static void do_run(const char *path, const char *runtime_dir)
{
    char *raw = read_file(path);
    if (!raw) exit(1);
    MojoStr *src    = mojo_str_new(raw);  free(raw);
    MojoStr *gimple = mojo_gimple(src);

    char out[256];
    snprintf(out, sizeof(out), "/tmp/mojo_run_%d", (int)getpid());

    int rc = compile_gimple_to_elf(mojo_str_data(gimple), out, runtime_dir);
    if (rc != 0) { fprintf(stderr, "mojo run: compilation failed\n"); exit(rc); }

    rc = system(out);
    unlink(out);
    exit(WEXITSTATUS(rc));
}

/* ── main ────────────────────────────────────────────────────────────────*/

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "mojo: missing command\nUse 'mojo --help'\n");
        return 1;
    }

    /* Runtime dir: MOJO_HOME env, else relative to where binary lives.
     * Haiku: refine with realpath(argv[0]) if needed. */
    const char *runtime_dir = getenv("MOJO_HOME");
    if (!runtime_dir) runtime_dir = "runtime";

    const char *cmd = argv[1];

    if (!strcmp(cmd, "--version") || !strcmp(cmd, "-v")) {
        printf("mojo %s (self-hosting)\n", VERSION);
        return 0;
    }
    if (!strcmp(cmd, "--help") || !strcmp(cmd, "-h")) {
        print_help();
        return 0;
    }
    if (!strncmp(cmd, "--dump-", 7)) {
        if (argc < 3) { fprintf(stderr, "mojo %s: no input file\n", cmd); return 1; }
        do_dump(cmd, argv[2]);
        return 0;
    }
    if (!strcmp(cmd, "build")) {
        do_build(argc - 2, argv + 2, runtime_dir);
        return 0;
    }
    if (!strcmp(cmd, "run")) {
        if (argc < 3) { fprintf(stderr, "mojo run: no input file\n"); return 1; }
        do_run(argv[2], runtime_dir);
        /* do_run exits */
    }
    /* Shorthand: mojo file.mojo */
    if (strstr(cmd, ".mojo")) {
        do_run(cmd, runtime_dir);
        /* do_run exits */
    }

    fprintf(stderr, "mojo: unknown command '%s'\nUse 'mojo --help'\n", cmd);
    return 1;
}
