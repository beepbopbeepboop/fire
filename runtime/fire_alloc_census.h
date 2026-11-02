/* fire_alloc_census.h -- opt-in allocation census for the C runtime.

   Built only with -DMOJO_ALLOC_CENSUS. Without that flag this header expands
   to nothing and the runtime is byte-for-byte the same translation unit it was.

   Purpose: bugs/mid/CODEGEN_bootstrap_resource_blowup.md, plan step 1. The
   self-hosted compiler never frees, so "what is still live" is the question
   that decides between an AST-lifetime fix and a temporaries fix. This census
   answers it per CALL SITE: for every malloc/calloc/realloc/free made from
   fire_runtime.c (and from anything that includes it), it keeps

     live_objs   allocations from this site not yet freed
     live_bytes  the bytes those allocations asked for
     total       every allocation this site ever made

   and prints one row per site, largest live_bytes first, to stderr at exit:

     alloc-census live_objs=<n> live_bytes=<n> total=<n> <file>:<line>

   Design constraints, each because the census must not change what it counts:

   - The block layout is untouched (no header in front of the block). The
     runtime decides "is this a malloc'd string" with malloc_size() on the
     pointer it holds (fire_runtime.c, mojo_boxed_is_str), so a prefix header
     would make every runtime string look like a literal and change behaviour.
     Instead each live pointer is recorded in a side table keyed by address.
   - The census's own storage comes from the real libc allocator (the
     definitions below run before the macros that redirect the runtime).
   - Single-threaded, like the rest of the runtime (see fire_runtime.c's
     notes on the cooperative coroutine scheduler).

   Include this header LAST among the runtime's includes: the macros at the
   bottom redirect every later call in the translation unit. */

#ifndef FIRE_ALLOC_CENSUS_H
#define FIRE_ALLOC_CENSUS_H

#ifdef MOJO_ALLOC_CENSUS

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#define MOJO_CENSUS_SITE_CAP  (1u << 14)   /* distinct (file, line) call sites */

typedef struct {
    const char *file;
    int         line;
    uint64_t    live_objs;
    uint64_t    live_bytes;
    uint64_t    total;
} MojoCensusSite;

typedef struct {
    void    *ptr;     /* NULL = empty slot */
    size_t   bytes;
    uint32_t site;    /* index into _cs_sites */
} MojoCensusLive;

static MojoCensusSite *_cs_sites;
static uint32_t         _cs_nsites;
static MojoCensusLive  *_cs_live;
static size_t           _cs_live_cap;   /* power of two, or 0 */
static size_t           _cs_live_n;
static int              _cs_armed;

static size_t _cs_ptr_slot(const void *p, size_t mask)
{
    return (size_t)((((uintptr_t)p) >> 4) * 0x9E3779B97F4A7C15ull) & mask;
}

static void _cs_report(void);

static void _cs_arm(void)
{
    if (_cs_armed) return;
    _cs_armed = 1;
    _cs_sites = (MojoCensusSite *)calloc(MOJO_CENSUS_SITE_CAP, sizeof(MojoCensusSite));
    _cs_live_cap = 1u << 16;
    _cs_live = (MojoCensusLive *)calloc(_cs_live_cap, sizeof(MojoCensusLive));
    atexit(_cs_report);
}

static uint32_t _cs_site(const char *file, int line)
{
    size_t h = ((size_t)(uintptr_t)file * 31u + (size_t)line) & (MOJO_CENSUS_SITE_CAP - 1);
    for (;;) {
        MojoCensusSite *s = &_cs_sites[h];
        if (s->file == NULL) {
            s->file = file;
            s->line = line;
            _cs_nsites++;
            return (uint32_t)h;
        }
        if (s->line == line && strcmp(s->file, file) == 0)
            return (uint32_t)h;
        h = (h + 1) & (MOJO_CENSUS_SITE_CAP - 1);
    }
}

static void _cs_live_grow(void);

static void _cs_live_put(void *p, size_t bytes, uint32_t site)
{
    if ((_cs_live_n + 1) * 2 > _cs_live_cap)
        _cs_live_grow();
    size_t mask = _cs_live_cap - 1, i = _cs_ptr_slot(p, mask);
    while (_cs_live[i].ptr != NULL)
        i = (i + 1) & mask;
    _cs_live[i].ptr = p;
    _cs_live[i].bytes = bytes;
    _cs_live[i].site = site;
    _cs_live_n++;
}

static void _cs_live_grow(void)
{
    MojoCensusLive *old = _cs_live;
    size_t oldcap = _cs_live_cap;
    _cs_live_cap = oldcap * 2;
    _cs_live = (MojoCensusLive *)calloc(_cs_live_cap, sizeof(MojoCensusLive));
    _cs_live_n = 0;
    for (size_t j = 0; j < oldcap; j++)
        if (old[j].ptr != NULL) {
            size_t mask = _cs_live_cap - 1, i = _cs_ptr_slot(old[j].ptr, mask);
            while (_cs_live[i].ptr != NULL)
                i = (i + 1) & mask;
            _cs_live[i] = old[j];
            _cs_live_n++;
        }
    free(old);
}

/* Remove p from the live table (backward-shift deletion keeps probe chains
   intact, so no tombstones accumulate). Returns 1 and fills bytes/site when p
   was a census allocation, 0 otherwise. */
static int _cs_live_take(void *p, size_t *bytes, uint32_t *site)
{
    if (_cs_live_n == 0)
        return 0;
    size_t mask = _cs_live_cap - 1, i = _cs_ptr_slot(p, mask);
    while (_cs_live[i].ptr != p) {
        if (_cs_live[i].ptr == NULL)
            return 0;
        i = (i + 1) & mask;
    }
    *bytes = _cs_live[i].bytes;
    *site = _cs_live[i].site;
    _cs_live[i].ptr = NULL;
    _cs_live_n--;
    size_t hole = i;
    for (size_t j = (i + 1) & mask; _cs_live[j].ptr != NULL; j = (j + 1) & mask) {
        size_t home = _cs_ptr_slot(_cs_live[j].ptr, mask);
        /* Move the entry into the hole unless its home lies cyclically in (hole, j]. */
        int stays = (hole <= j) ? (home > hole && home <= j) : (home > hole || home <= j);
        if (!stays) {
            _cs_live[hole] = _cs_live[j];
            _cs_live[j].ptr = NULL;
            hole = j;
        }
    }
    return 1;
}

static void *mojo_census_malloc(size_t n, const char *file, int line)
{
    void *p;
    _cs_arm();
    p = malloc(n);
    if (p != NULL) {
        uint32_t s = _cs_site(file, line);
        _cs_sites[s].live_objs++;
        _cs_sites[s].live_bytes += n;
        _cs_sites[s].total++;
        _cs_live_put(p, n, s);
    }
    return p;
}

static void *mojo_census_calloc(size_t count, size_t size, const char *file, int line)
{
    void *p;
    _cs_arm();
    p = calloc(count, size);
    if (p != NULL) {
        size_t n = count * size;
        uint32_t s = _cs_site(file, line);
        _cs_sites[s].live_objs++;
        _cs_sites[s].live_bytes += n;
        _cs_sites[s].total++;
        _cs_live_put(p, n, s);
    }
    return p;
}

static void mojo_census_free(void *p)
{
    size_t bytes;
    uint32_t s;
    if (p == NULL)
        return;
    if (_cs_live_take(p, &bytes, &s)) {
        _cs_sites[s].live_objs--;
        _cs_sites[s].live_bytes -= bytes;
    }
    free(p);
}

static void *mojo_census_realloc(void *p, size_t n, const char *file, int line)
{
    size_t oldbytes;
    uint32_t olds;
    void *q;
    if (p == NULL)
        return mojo_census_malloc(n, file, line);
    _cs_arm();
    q = realloc(p, n);
    if (q == NULL)
        return NULL;   /* p is still valid and still live: leave the table alone */
    if (_cs_live_take(p, &oldbytes, &olds)) {
        _cs_sites[olds].live_objs--;
        _cs_sites[olds].live_bytes -= oldbytes;
    }
    if (n > 0) {
        uint32_t s = _cs_site(file, line);
        _cs_sites[s].live_objs++;
        _cs_sites[s].live_bytes += n;
        _cs_sites[s].total++;
        _cs_live_put(q, n, s);
    }
    return q;
}

static int _cs_by_live_bytes(const void *a, const void *b)
{
    const MojoCensusSite *x = &_cs_sites[*(const uint32_t *)a];
    const MojoCensusSite *y = &_cs_sites[*(const uint32_t *)b];
    if (x->live_bytes != y->live_bytes)
        return x->live_bytes < y->live_bytes ? 1 : -1;
    return (int)(*(const uint32_t *)a) - (int)(*(const uint32_t *)b);
}

static void _cs_report(void)
{
    uint32_t *order;
    uint32_t n = 0, i;
    uint64_t objs = 0, bytes = 0, total = 0;
    if (!_cs_armed)
        return;
    order = (uint32_t *)malloc(sizeof(uint32_t) * (size_t)MOJO_CENSUS_SITE_CAP);
    for (i = 0; i < MOJO_CENSUS_SITE_CAP; i++)
        if (_cs_sites[i].file != NULL) {
            order[n++] = i;
            objs += _cs_sites[i].live_objs;
            bytes += _cs_sites[i].live_bytes;
            total += _cs_sites[i].total;
        }
    qsort(order, n, sizeof(uint32_t), _cs_by_live_bytes);
    fprintf(stderr, "alloc-census sites=%u live_objs=%llu live_bytes=%llu total=%llu\n",
            (unsigned)n, (unsigned long long)objs, (unsigned long long)bytes,
            (unsigned long long)total);
    for (i = 0; i < n; i++) {
        const MojoCensusSite *s = &_cs_sites[order[i]];
        fprintf(stderr, "alloc-census live_objs=%llu live_bytes=%llu total=%llu %s:%d\n",
                (unsigned long long)s->live_objs, (unsigned long long)s->live_bytes,
                (unsigned long long)s->total, s->file, s->line);
    }
    free(order);
}

/* Redirect every later call in this translation unit. */
#define malloc(n)            mojo_census_malloc((n), __FILE__, __LINE__)
#define calloc(c, s)         mojo_census_calloc((c), (s), __FILE__, __LINE__)
#define realloc(p, n)        mojo_census_realloc((p), (n), __FILE__, __LINE__)
#define free(p)              mojo_census_free((p))

#endif /* MOJO_ALLOC_CENSUS */
#endif /* FIRE_ALLOC_CENSUS_H */
