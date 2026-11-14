/* fire_alloc_census.h -- opt-in allocation census for the C runtime and for the
   emitted translation units that include fire_runtime.h.

   Built only with -DMOJO_ALLOC_CENSUS. Without that flag this header expands
   to nothing and every translation unit is the same as it was.

   Purpose: bugs/hard/CODEGEN_bootstrap_resource_blowup.md, plan step 1. The
   self-hosted compiler never frees, so "what is still live" is the question
   that decides between an AST-lifetime fix and a temporaries fix. This census
   answers it per CALL SITE: for every malloc/calloc/realloc/free made from any
   translation unit built with the flag (the runtime itself, and every emitted
   .ci that includes fire_runtime.h), it keeps

     live_objs   allocations from this site not yet freed
     live_bytes  the bytes those allocations asked for
     total       every allocation this site ever made

   and prints one row per site, largest live_bytes first, to stderr at exit:

     alloc-census live_objs=<n> live_bytes=<n> total=<n> <file>:<line>

   ONE DEFINITION. The state and the bodies live in runtime/fire_runtime.c, the
   one translation unit that is the runtime's object file. This header is only
   the declarations and the redirect macros, so every translation unit that
   includes it calls the same live table. A per-translation-unit copy would
   miss a block allocated in one .ci and freed in another (the free's table
   would never see it) and would print one report per unit.

   Design constraints, each because the census must not change what it counts:

   - The block layout is untouched (no header in front of the block). The
     runtime decides "is this a malloc'd string" with malloc_size() on the
     pointer it holds (fire_runtime.c, mojo_boxed_is_str), so a prefix header
     would make every runtime string look like a literal and change behaviour.
     Instead each live pointer is recorded in a side table keyed by address.
   - The census's own storage comes from the real libc allocator. The
     definitions in fire_runtime.c reach it as (malloc)(n), which is not
     expanded by the redirect macros below.
   - Single-threaded, like the rest of the runtime (see fire_runtime.c's
     notes on the cooperative coroutine scheduler).

   The redirect macros are C only. A C++ translation unit that includes
   fire_runtime.h still gets the prototypes, but its own malloc/free calls are
   not counted: redirecting them would rewrite the standard C++ headers that
   follow. */

#ifndef FIRE_ALLOC_CENSUS_H
#define FIRE_ALLOC_CENSUS_H

#ifdef MOJO_ALLOC_CENSUS

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

void *mojo_census_malloc(size_t n, const char *file, int line);
void *mojo_census_calloc(size_t count, size_t size, const char *file, int line);
void *mojo_census_realloc(void *p, size_t n, const char *file, int line);
void  mojo_census_free(void *p);

#ifndef __cplusplus
/* Redirect every later call in the translation unit that includes this
   header. Include it only after the system headers, as fire_runtime.c does. */
/* The arguments are NOT parenthesised: a parenthesised operand is `expected
   expression before '('` inside a `__GIMPLE` body, and the emitted .ci calls
   malloc/free there. A call argument needs no protective parentheses (only a
   comma operator could differ, and none is passed to these). */
#define malloc(n)            mojo_census_malloc(n, __FILE__, __LINE__)
#define calloc(c, s)         mojo_census_calloc(c, s, __FILE__, __LINE__)
#define realloc(p, n)        mojo_census_realloc(p, n, __FILE__, __LINE__)
#define free(p)              mojo_census_free(p)
#endif

#ifdef __cplusplus
}
#endif

#endif /* MOJO_ALLOC_CENSUS */
#endif /* FIRE_ALLOC_CENSUS_H */
