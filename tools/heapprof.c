/* heapprof: a sampling live-heap profiler for macOS, injected with DYLD_INSERT_LIBRARIES.
 *
 * Why this exists: `leaks` only reports UNREACHABLE memory, and MallocStackLogging on a
 * whole-closure compiler run (hundreds of millions of allocations, tens of GB live) is
 * itself a multi-ten-GB job.  A compiler with no collector keeps most of its garbage
 * *reachable* (registries, caches, AST/type tables), so the question is "which allocation
 * sites hold the live bytes", not "what is unreachable".  This answers that at ~10-30%
 * overhead and a few MB of profiler memory.
 *
 * Method (the same one heapprof/tcmalloc use): every allocation of size s is sampled with
 * probability min(1, s / HEAPPROF_INTERVAL).  A sampled block is recorded (ptr -> size,
 * stack) and forgotten when it is freed; an allocation stack's estimate of live bytes is
 * sum(max(size, INTERVAL)) over its live sampled blocks, an unbiased estimator.  Stacks
 * are captured by walking frame pointers (arm64 Darwin mandates them), so no allocation
 * happens while profiling.
 *
 * Build:  cc -O2 -dynamiclib -o build/heapprof.dylib tools/heapprof.c
 * Use:    DYLD_INSERT_LIBRARIES=build/heapprof.dylib HEAPPROF_OUT=prefix ./prog ...
 * Env:    HEAPPROF_OUT       output prefix (default ./heapprof); files are <prefix>.<pid>.<n>.txt
 *         HEAPPROF_ONLY      only profile processes whose name contains this (skips a wrapper's own python)
 *         HEAPPROF_INTERVAL  mean bytes between samples (default 65536)
 *         HEAPPROF_STEP_MB   write a snapshot each time the live estimate has grown by this
 *                            much since the last one (default 2048); a final one is written at
 *                            exit and on SIGUSR1.
 * Report: python3 tools/heapprof_report.py <snapshot.txt> [--binary ./prog] [--top N]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <signal.h>
#include <sys/ucontext.h>
#include <pthread.h>
#include <malloc/malloc.h>
#include <sys/mman.h>
#include <mach-o/dyld.h>
#include <dlfcn.h>
#include <crt_externs.h>

#define MAXDEPTH 14
#define SKIP 2                      /* our own frames */

typedef struct { uint64_t ptr; uint64_t size; uint32_t stack; uint32_t cnt; } Blk;
typedef struct {
    uint64_t pcs[MAXDEPTH];
    uint64_t live_bytes, live_count;   /* estimated, scaled */
    uint64_t tot_bytes, tot_count;     /* estimated, scaled, over the whole run */
    uint32_t hash; uint32_t depth;
} Stack;

static Blk *blks;      static size_t blk_cap = 1u << 22, blk_used;
static Stack *stacks;  static size_t stk_cap = 1u << 18, stk_used;
static uint32_t *stk_idx; static size_t stk_idx_cap = 1u << 19;
static uint64_t interval = 65536, step_bytes = 2048ull << 20;
static uint64_t live_est, next_snap, total_allocs, total_sampled;
static uint64_t rng = 88172645463325252ull;
static char out_prefix[1024] = "./heapprof";
static int snap_no;
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static __thread int busy;
static int inited;

/* ---- optional use-after-free / double-free detector (HEAPPROF_QUARANTINE=N) ----
 * Every freed block is filled with 0xDF and held back in a ring of the N most recent frees before it
 * is really freed.  When a block leaves the ring (and for every block still in it at a crash or exit)
 * its fill is checked: a changed byte means something WROTE to it after free, and the report names the
 * stack that freed it.  A block freed while still in the ring is a double free.  Readers of a freed
 * block see 0xDF pointers, which crash close to the bug instead of far from it. */
typedef struct { uint64_t ptr; uint32_t size; uint32_t pad; uint64_t seq; uint64_t pcs[8]; } QEnt;
static QEnt *qring; static uint64_t q_n, q_head, q_count;
static uint64_t *qset; static size_t qset_cap;
static uint64_t uaf_found, q_seq, q_trap_seq;
volatile uint64_t hp_trap_addr;      /* set just before the deliberate SIGTRAP of HEAPPROF_TRAP_SEQ (read it from lldb) */
static inline size_t qh(uint64_t p) { return (size_t)((p >> 4) * 0x9E3779B97F4A7C15ull >> 20) & (qset_cap - 1); }
static void qset_add(uint64_t p) { size_t j = qh(p); while (qset[j]) j = (j + 1) & (qset_cap - 1); qset[j] = p; }
static void qset_del(uint64_t p) {
    size_t m = qset_cap - 1, j = qh(p);
    while (qset[j] && qset[j] != p) j = (j + 1) & m;
    if (!qset[j]) return;
    size_t i = j, k = j;
    for (;;) {
        k = (k + 1) & m;
        if (!qset[k]) break;
        size_t h = qh(qset[k]);
        if (((k - h) & m) >= ((k - i) & m)) { qset[i] = qset[k]; i = k; }
    }
    qset[i] = 0;
}
static int qset_has(uint64_t p) { size_t m = qset_cap - 1, j = qh(p); while (qset[j]) { if (qset[j] == p) return 1; j = (j + 1) & m; } return 0; }
static uint64_t crash_pcs[64]; static int crash_n;
static void heapprof_snapshot(const char *why);
static int mu_held_by_reporter;
static void uaf_report(QEnt *e, size_t off, const char *what) {
    mu_held_by_reporter = 1;
    fprintf(stderr, "heapprof: %s: block %p size %u, first bad byte at +%zu, freed as free #%llu\n", what, (void *)e->ptr, e->size, off, (unsigned long long)e->seq);
    crash_n = 0;
    for (int k = 0; k < 8 && e->pcs[k]; k++) crash_pcs[crash_n++] = e->pcs[k];
    uaf_found = 1;
    heapprof_snapshot("WRITE-AFTER-FREE (CRASH stack below is where it was FREED)");
    abort();
}
static void q_check(QEnt *e) {
    unsigned char *b = (unsigned char *)e->ptr;
    for (size_t i = 0; i < e->size; i++) if (b[i] != 0xDF) uaf_report(e, i, "WRITE AFTER FREE");
}
static void q_check_all(void) {
    if (!q_n) return;
    for (uint64_t i = 0; i < q_count; i++) q_check(&qring[(q_head + q_n - q_count + i) % q_n]);
}

static void *xmap(size_t n) {
    void *p = mmap(0, n, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
    if (p == MAP_FAILED) { write(2, "heapprof: mmap failed\n", 22); _exit(99); }
    return p;
}

static void on_sig(int s) { (void)s; heapprof_snapshot("SIGUSR1"); }
static void on_crash(int s, siginfo_t *si, void *ctx) {   /* a compiler that dies at its peak still leaves its profile */
    ucontext_t *uc = (ucontext_t *)ctx;
    crash_pcs[crash_n++] = (uint64_t)__darwin_arm_thread_state64_get_pc(uc->uc_mcontext->__ss);
    uintptr_t *fp = (uintptr_t *)__darwin_arm_thread_state64_get_fp(uc->uc_mcontext->__ss);
    while (fp && ((uintptr_t)fp & 7) == 0 && crash_n < 64) {
        uintptr_t ret = fp[1]; uintptr_t *next = (uintptr_t *)fp[0];
        if (!ret) break;
        crash_pcs[crash_n++] = ret;
        if (next <= fp || (uintptr_t)next - (uintptr_t)fp > (1u << 24)) break;
        fp = next;
    }
    (void)si;
    if (q_n && !uaf_found) {                      /* a write-after-free that caused this crash reports itself */
        uint64_t save[64]; int saven = crash_n; memcpy(save, crash_pcs, sizeof save);
        q_check_all();                            /* aborts (with the free stack) on a finding */
        crash_n = saven; memcpy(crash_pcs, save, sizeof save);
    }
    heapprof_snapshot(s == SIGSEGV ? "SIGSEGV" : s == SIGBUS ? "SIGBUS" : "SIGTRAP");
    signal(s, SIG_DFL); raise(s);
}
static void on_exit_(void) { q_check_all(); heapprof_snapshot("exit"); }

__attribute__((constructor)) static void hp_init(void) {
    const char *e;
    if ((e = getenv("HEAPPROF_ONLY"))) {          /* profile only processes whose name contains this */
        const char *pn = *_NSGetProgname();
        if (!pn || !strstr(pn, e)) return;
    }
    if ((e = getenv("HEAPPROF_OUT"))) snprintf(out_prefix, sizeof out_prefix, "%s", e);
    if ((e = getenv("HEAPPROF_INTERVAL"))) interval = strtoull(e, 0, 10);
    if ((e = getenv("HEAPPROF_STEP_MB"))) step_bytes = strtoull(e, 0, 10) << 20;
    if ((e = getenv("HEAPPROF_QUARANTINE"))) {
        q_n = strtoull(e, 0, 10);
        if ((e = getenv("HEAPPROF_TRAP_SEQ"))) q_trap_seq = strtoull(e, 0, 10);
        if (q_n) {
            qring = xmap(q_n * sizeof(QEnt));
            qset_cap = 1; while (qset_cap < q_n * 2) qset_cap <<= 1;
            qset = xmap(qset_cap * 8);
        }
    }
    blks = xmap(blk_cap * sizeof(Blk));
    stacks = xmap(stk_cap * sizeof(Stack));
    stk_idx = xmap(stk_idx_cap * sizeof(uint32_t));
    next_snap = step_bytes;
    signal(SIGUSR1, on_sig);
    {   /* alternate stack so a stack-overflow crash can still write its snapshot */
        stack_t ss; ss.ss_sp = xmap(1 << 20); ss.ss_size = 1 << 20; ss.ss_flags = 0;
        sigaltstack(&ss, 0);
        struct sigaction sa; memset(&sa, 0, sizeof sa);
        sa.sa_sigaction = on_crash; sa.sa_flags = SA_ONSTACK | SA_SIGINFO; sigemptyset(&sa.sa_mask);
        sigaction(SIGSEGV, &sa, 0); sigaction(SIGBUS, &sa, 0); sigaction(SIGTRAP, &sa, 0); sigaction(SIGILL, &sa, 0);
    }
    atexit(on_exit_);
    inited = 1;
}

static inline uint64_t rnd(void) { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return rng; }

/* ---- pointer table: open addressing, linear probing, backward-shift deletion ---- */
static inline size_t bh(uint64_t p) { return (size_t)((p >> 4) * 0x9E3779B97F4A7C15ull >> 20) & (blk_cap - 1); }

static void blk_grow(void) {
    size_t oc = blk_cap; Blk *ob = blks;
    blk_cap *= 2; blks = xmap(blk_cap * sizeof(Blk));
    for (size_t i = 0; i < oc; i++) if (ob[i].ptr) {
        size_t j = bh(ob[i].ptr); while (blks[j].ptr) j = (j + 1) & (blk_cap - 1);
        blks[j] = ob[i];
    }
    munmap(ob, oc * sizeof(Blk));
}

static uint32_t stack_intern(uint64_t *pcs, uint32_t depth, uint64_t weight_bytes) {
    uint32_t h = 2166136261u;
    for (uint32_t i = 0; i < depth; i++) { h ^= (uint32_t)(pcs[i] ^ (pcs[i] >> 32)); h *= 16777619u; }
    size_t m = stk_idx_cap - 1, j = h & m;
    for (;;) {
        uint32_t v = stk_idx[j];
        if (!v) break;
        Stack *s = &stacks[v - 1];
        if (s->hash == h && s->depth == depth && !memcmp(s->pcs, pcs, depth * 8)) return v - 1;
        j = (j + 1) & m;
    }
    if (stk_used + 1 >= stk_cap || stk_used * 2 >= stk_idx_cap) return 0xffffffffu;   /* table full: drop */
    Stack *s = &stacks[stk_used];
    memcpy(s->pcs, pcs, depth * 8); s->depth = depth; s->hash = h;
    stk_idx[j] = (uint32_t)(++stk_used);
    (void)weight_bytes;
    return (uint32_t)(stk_used - 1);
}

static uint32_t capture_skip(uint64_t *pcs, int skip0) {
    uintptr_t *fp = (uintptr_t *)__builtin_frame_address(0);
    uint32_t n = 0; int skip = skip0;
    while (fp && ((uintptr_t)fp & 7) == 0 && n < MAXDEPTH) {
        uintptr_t *next = (uintptr_t *)fp[0];
        uintptr_t ret = fp[1];
        if (!ret) break;
        if (skip > 0) skip--; else pcs[n++] = (uint64_t)ret;
        if (next <= fp || (uintptr_t)next - (uintptr_t)fp > (1u << 24)) break;
        fp = next;
    }
    return n;
}

static uint32_t capture(uint64_t *pcs) { return capture_skip(pcs, SKIP); }

static inline void note_alloc(void *p, size_t size) {
    if (!p || !inited || busy) return;
    __atomic_add_fetch(&total_allocs, 1, __ATOMIC_RELAXED);
    uint64_t w = size >= interval ? size : interval;
    if (size < interval && (rnd() % interval) >= size) return;   /* not sampled */
    busy = 1;
    pthread_mutex_lock(&mu);
    uint64_t pcs[MAXDEPTH]; uint32_t d = capture(pcs);
    uint32_t sid = stack_intern(pcs, d, w);
    if (sid != 0xffffffffu) {
        if ((blk_used + 1) * 2 > blk_cap) blk_grow();
        size_t j = bh((uint64_t)p); while (blks[j].ptr) j = (j + 1) & (blk_cap - 1);
        blks[j].ptr = (uint64_t)p; blks[j].size = w; blks[j].stack = sid; blks[j].cnt = (uint32_t)(size >= interval ? 1 : interval / (size ? size : 1)); blk_used++;
        Stack *s = &stacks[sid];
        uint64_t cnt = blks[j].cnt;
        s->live_bytes += w; s->live_count += cnt; s->tot_bytes += w; s->tot_count += cnt;
        live_est += w; total_sampled++;
    }
    int snap = live_est >= next_snap;
    pthread_mutex_unlock(&mu);
    busy = 0;
    if (snap) { next_snap = live_est + step_bytes; heapprof_snapshot("growth"); }
}

static inline void note_free(void *p) {
    if (!p || !inited || busy || !blk_used) return;
    pthread_mutex_lock(&mu);
    size_t m = blk_cap - 1, j = bh((uint64_t)p);
    while (blks[j].ptr) {
        if (blks[j].ptr == (uint64_t)p) {
            Blk b = blks[j]; Stack *s = &stacks[b.stack];
            s->live_bytes -= b.size; live_est -= b.size;
            s->live_count -= b.cnt;
            blk_used--;
            /* backward-shift delete */
            size_t i = j, k = j;
            for (;;) {
                k = (k + 1) & m;
                if (!blks[k].ptr) break;
                size_t h = bh(blks[k].ptr);
                if (((k - h) & m) >= ((k - i) & m)) { blks[i] = blks[k]; i = k; }
            }
            blks[i].ptr = 0;
            break;
        }
        j = (j + 1) & m;
    }
    pthread_mutex_unlock(&mu);
}

static void heapprof_snapshot(const char *why) {
    if (!inited) return;
    char path[1200];
    snprintf(path, sizeof path, "%s.%d.%d.txt", out_prefix, (int)getpid(), snap_no++);
    busy = 1;
    FILE *f = fopen(path, "w");
    if (f) {
        if (!mu_held_by_reporter) pthread_mutex_lock(&mu);
        fprintf(f, "# heapprof snapshot why=%s live_est=%llu allocs=%llu sampled=%llu interval=%llu stacks=%zu\n",
                why, (unsigned long long)live_est, (unsigned long long)total_allocs,
                (unsigned long long)total_sampled, (unsigned long long)interval, stk_used);
        uint32_t nimg = _dyld_image_count();
        for (uint32_t i = 0; i < nimg; i++) {
            const char *nm = _dyld_get_image_name(i);
            if (nm && !strstr(nm, "/usr/lib/") && !strstr(nm, "/System/"))
                fprintf(f, "IMAGE %u 0x%llx %s\n", i, (unsigned long long)(uintptr_t)_dyld_get_image_header(i), nm);
        }
        for (size_t i = 0; i < stk_used; i++) {
            Stack *s = &stacks[i];
            if (!s->tot_bytes) continue;
            fprintf(f, "S %llu %llu %llu %llu", (unsigned long long)s->live_bytes, (unsigned long long)s->live_count,
                    (unsigned long long)s->tot_bytes, (unsigned long long)s->tot_count);
            for (uint32_t k = 0; k < s->depth; k++) fprintf(f, " 0x%llx", (unsigned long long)s->pcs[k]);
            fputc('\n', f);
        }
        if (!mu_held_by_reporter) pthread_mutex_unlock(&mu);
        if (crash_n) {
            fprintf(f, "CRASH");
            for (int k = 0; k < crash_n; k++) fprintf(f, " 0x%llx", (unsigned long long)crash_pcs[k]);
            fputc('\n', f);
        }
        fclose(f);
    }
    busy = 0;
}

/* ---- interposed entry points ---- */
static void *hp_malloc(size_t n) { void *p = malloc(n); note_alloc(p, n); return p; }
static void *hp_calloc(size_t a, size_t b) { void *p = calloc(a, b); note_alloc(p, a * b); return p; }
static void q_free(void *p) {                    /* the quarantining free */
    if (!p) return;
    uint64_t up = (uint64_t)(uintptr_t)p;
    size_t sz = malloc_size(p);
    if (!sz || busy) { free(p); return; }
    pthread_mutex_lock(&mu);
    if (qset_has(up)) {
        for (uint64_t i = 0; i < q_count; i++) {
            QEnt *e = &qring[(q_head + q_n - q_count + i) % q_n];
            if (e->ptr == up) { pthread_mutex_unlock(&mu); uaf_report(e, 0, "DOUBLE FREE (earlier free shown)"); }
        }
    }
    memset(p, 0xDF, sz);
    q_seq++;
    if (q_trap_seq && q_seq == q_trap_seq) {      /* stop the debugger AT the free that the write-after-free report named */
        hp_trap_addr = up;
        fprintf(stderr, "heapprof: TRAP at free #%llu of block %p size %zu\n", (unsigned long long)q_seq, p, sz);
        __builtin_debugtrap();
    }
    if (q_count == q_n) {                         /* evict the oldest */
        QEnt *o = &qring[q_head];
        q_check(o);
        qset_del(o->ptr);
        void *op = (void *)(uintptr_t)o->ptr;
        free(op);
        q_count--;
    }
    QEnt *e = &qring[q_head];
    e->ptr = up; e->size = (uint32_t)sz; e->seq = q_seq;
    uint64_t pcs[MAXDEPTH]; uint32_t d = capture_skip(pcs, 0);
    memset(e->pcs, 0, sizeof e->pcs);
    for (uint32_t k = 0; k < d && k < 8; k++) e->pcs[k] = pcs[k];
    qset_add(up);
    q_head = (q_head + 1) % q_n; q_count++;
    pthread_mutex_unlock(&mu);
}
static void hp_free(void *p) { note_free(p); if (q_n) q_free(p); else free(p); }
static void *hp_realloc(void *o, size_t n) {
    if (o) note_free(o);
    if (q_n && o) {
        size_t os = malloc_size(o);
        void *p = malloc(n ? n : 1);
        if (p) memcpy(p, o, os < n ? os : n);
        note_alloc(p, n);
        q_free(o);
        return p;
    }
    void *p = realloc(o, n); note_alloc(p, n); return p;
}
static void *hp_valloc(size_t n) { void *p = valloc(n); note_alloc(p, n); return p; }
static int hp_posix_memalign(void **r, size_t al, size_t n) { int e = posix_memalign(r, al, n); if (!e) note_alloc(*r, n); return e; }
static char *hp_strdup(const char *s) { char *p = strdup(s); note_alloc(p, strlen(s) + 1); return p; }

#define INTERPOSE(rep, orig) \
    __attribute__((used)) static struct { const void *r; const void *o; } _ip_##orig \
    __attribute__((section("__DATA,__interpose"))) = { (const void *)(uintptr_t)&rep, (const void *)(uintptr_t)&orig }
INTERPOSE(hp_malloc, malloc);
INTERPOSE(hp_calloc, calloc);
INTERPOSE(hp_realloc, realloc);
INTERPOSE(hp_free, free);
INTERPOSE(hp_valloc, valloc);
INTERPOSE(hp_posix_memalign, posix_memalign);
INTERPOSE(hp_strdup, strdup);
