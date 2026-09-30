# RUNTIME: `mojo_{list,dict,set}_free` never unregister from the kind-registries — latent type-confusion on address reuse

## Status (2026-09-24 — RESOLVED, verified against current `runtime/fire_runtime.c`)

The fix this doc calls for is PRESENT in the current runtime (the file was
renamed `runtime/mojo_runtime.c` -> `runtime/fire_runtime.c` since this doc
was written). Each container's `_destroy` helper now discards its own
address from every registry it was added to, and `mojo_*_free` routes
through it:

- `mojo_list_destroy` (`fire_runtime.c:578`): discards from
  `_mojo_list_registry` AND `_mojo_tuple_registry`, then `free(l->data)`.
- `mojo_dict_destroy` (`:2548`): discards from `_mojo_dict_registry` and
  `_mojo_bool_dict_registry`.
- `mojo_set_destroy` (`:3022`): discards from `_mojo_set_registry`, guarded
  by `_mojo_set_registry_busy` (a set's own discard must not recurse into
  the registry).

`mojo_set_discard_int`/`_str` (`:3200`-ish) are NULL-safe and tolerate an
absent value (`if (idx < 0 || s->slots[idx].tag != ...) return;`), so the
discard is a no-op for a never-registered or already-removed container —
the sanity-check this doc explicitly asked for. The companion
`CODEGEN_container_no_deallocation_unbounded_growth.md` is also fixed
(codegen now emits the cleanup calls), so this path is no longer "latent":
containers really are freed, and the discard is really exercised (verified
there by a flat-memory loop repro).

## Found 2026-09-15 (original text follows)
Found alongside
`CODEGEN_container_no_deallocation_unbounded_growth.md` while auditing
`runtime/mojo_runtime.c`'s container lifetime for that leak-check.
Currently **latent/unreachable** in practice because codegen never calls
these free functions at all (see the companion doc) — but it will become
live and dangerous the moment that companion bug is fixed, so it needs
fixing in the same pass, not discovered later as a fresh SIGBUS/type-
confusion mystery.

## What the bug is

`runtime/mojo_runtime.c` keeps three global `MojoSet` registries used to
runtime-discriminate an ambiguously-typed boxed pointer (a bare
`int64_t`/`void *` that could be a list, dict, set, or something else
entirely):

```c
static MojoSet *_mojo_list_registry = NULL;   // mojo_runtime.c:401
static MojoSet *_mojo_dict_registry = NULL;   // mojo_runtime.c:2415
static MojoSet *_mojo_set_registry  = NULL;   // mojo_runtime.c:2857
```

Each `mojo_list_new()` / `mojo_dict_new()` / `mojo_set_new()` adds its own
address to the matching registry (`mojo_runtime.c:473-474`, `:2429-2430`,
`:2875-2878`). But the matching free functions never remove it:

```c
void mojo_list_free(MojoList *l)     // mojo_runtime.c:478
{
    free(l->data);
    free(l);
    // _mojo_list_registry still contains (int64_t)(intptr_t)l
}

void mojo_dict_free(MojoDict *d)     // mojo_runtime.c:2434
{
    for (int64_t i = 0; i < d->cap; i++) free(d->slots[i].key);
    free(d->slots);
    free(d);
    // _mojo_dict_registry still contains (int64_t)(intptr_t)d
}

void mojo_set_free(MojoSet *s)       // mojo_runtime.c:2884
{
    for (int64_t i = 0; i < s->cap; i++)
        if (s->slots[i].tag == 1) free(s->slots[i].val_s);
    free(s->slots);
    free(s);
    // _mojo_set_registry still contains (int64_t)(intptr_t)s
}
```

Once a container is freed, `malloc`/`realloc` are free to hand that exact
address back out for the *next* allocation of any kind — another dict, a
`MojoStr`, a `MojoBoundMethod`, an unrelated struct. `mojo_is_registered_
list`/`_dict`/`_set` (used at `mojo_runtime.c:3232`, `:3236`, `:3246`,
`:3283`, `:3296`, `:4090` to decide how to `repr()`/iterate/typecheck a
boxed value) would then report the WRONG kind for that reused address —
e.g. a freshly-allocated `MojoStr` landing at a just-freed dict's old
address would still test positive for `mojo_is_registered_dict`, and
`_mojo_dispatch_getattr`/`repr()`/iteration would read it as dict slot
data instead of string data. This is the same class of memory
misinterpretation `mojo_runtime.c:2441-2449`'s comment already documents
happening once for real (the `.clear()` double-free SIGABRT) — a stale
registry entry pointing at reused memory is a variant of the same root
cause (a pointer identity check outliving the object it identifies).

## Where the fix goes

`runtime/mojo_runtime.c`:
- `mojo_list_free` needs `mojo_set_discard(_mojo_list_registry,
  (int64_t)(intptr_t)l)` before (or after) the `free(l)`.
- `mojo_dict_free` needs the same against `_mojo_dict_registry`.
- `mojo_set_free` needs the same against `_mojo_set_registry`.
- Check `mojo_set_discard`'s existing implementation
  (`runtime/mojo_runtime.h:614`) tolerates discarding a value that's
  already absent (it should, and should be a cheap no-op if the container
  was never actually registered — sanity-check this rather than assuming).
- Note `_mojo_tuple_registry` and `_mojo_bound_method_registry`
  (`mojo_runtime.c:431`, `:450`) have the exact same shape of bug for
  their own object kinds — tuples share `mojo_list_free`'s lifetime (a
  tuple IS a `MojoList*` per `mojo_mark_as_tuple`'s comment, so fixing
  `mojo_list_free` covers it), but `MojoBoundMethod` has no free function
  at all currently (not in scope for this doc — only worth fixing once
  bound methods are ever freed, which isn't happening yet either).

## Test case

Not independently reproducible today (codegen never calls the free
functions — see the companion doc), so today this can only be exercised
by calling the C runtime functions directly, not through a `.mojo` program:

```c
/* runtime/test_registry_dangling.c — new file, links against mojo_runtime.o */
#include "mojo_runtime.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    MojoDict *d = mojo_dict_new();
    int64_t addr = (int64_t)(intptr_t)d;
    mojo_dict_free(d);

    /* Force malloc to hand the same address back out for a non-dict
     * object of the same size class; on most allocators an immediate
     * same-size malloc after a free reuses the freed block. */
    void *reuse = malloc(sizeof(MojoDict));
    assert((int64_t)(intptr_t)reuse == addr && "allocator didn't reuse the freed address — retry with a tighter repro");

    /* BUG: registry still thinks the (now-reused, non-dict) address is a
     * live dict. */
    int is_dict = mojo_is_registered_dict(addr);
    printf("is_registered_dict after free+reuse: %d (expected 0)\n", is_dict);
    assert(is_dict == 0 && "stale registry entry outlived mojo_dict_free");
    return 0;
}
```

Expected once fixed: `mojo_is_registered_dict(addr)` returns `0`
immediately after `mojo_dict_free(d)`, regardless of whether the address
gets reused. Once `CODEGEN_container_no_deallocation_unbounded_growth.md`
is fixed and containers actually get freed by compiled programs, this
should also be re-checked end-to-end with a real `.mojo` repro that
creates-and-drops many containers of mixed kinds in a loop and asserts
`repr()`/`isinstance`-style behavior never misidentifies a live container's
kind.
