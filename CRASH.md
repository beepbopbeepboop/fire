# CRASH.md — `mojoc` segfaults on every input, including a two-line program

Branch `crash`, commit `19bc0dd`. Reproduced and root-caused to one runtime
predicate. **Not fixed** — this is a handoff.

## 1. The crash

```
$ printf 'def main():\n    print("hi")\n' > /tmp/tiny.mojo
$ ./mojoc --dump-full /tmp/tiny.mojo
Segmentation fault: 11
$ echo $?
139
```

Empty stdout, **empty stderr**. No diagnostic, no partial output. 100%
reproducible on a two-line program. Signal is SIGSEGV (11), shell status 139.

## 2. Blast radius in the gate

One root cause makes three registered steps red. They are marked
`expect=` in `tools/suite.py` and report as EXPECTED, and five more steps
skip behind them:

| step | state |
|---|---|
| `ab-native` | EXPECTED |
| `native-dumpfull` | EXPECTED |
| `bootstrap-stage2-dumps` | EXPECTED — all **45** sub-jobs `exit -11` |
| `bootstrap-stage2-transitive`, `bootstrap-stage3-dumps`, `bootstrap-stage3-transitive`, `bootstrap-verify`, `bootstrap-validate` | SKIP, all `dependency did not pass` |

So `make gate` currently reports `19 passed, 0 failed, 5 skipped, 3
expected-failure` — green *only* because those three are marked. Per
CLAUDE.md's anti-rot rule, **the moment the segfault stops they flip
themselves to FAIL.** Fixing this will turn the gate red until the
newly-reachable wave behind it is triaged. That is expected, not a
regression. Budget for it.

`mojoc` itself still **builds** (the `mojoc` step passes; it is the
*artifact* that crashes when run).

## 3. Root cause

A **16-bit pointer-range test used where a 47-bit one is required.**

Two predicates in the same runtime disagree about the same value:

`runtime/fire_runtime.c:4243` — the correct one:

```c
static int _mojo_tagged_addr_ok(int64_t addr)
{
    uint64_t u = (uint64_t)addr;
    if (u < 0x80000000ULL) return 0;                        /* < 2 GiB  */
    if (u >= 0x0000800000000000ULL) return 0;
    if (u & 7ULL) return 0;                                  /* aligned  */
#if MOJO_HAVE_MALLOC_USABLE_SIZE
    if (MOJO_MALLOC_USABLE_SIZE((void *)(intptr_t)u) < sizeof(int64_t)) return 0;
#endif
    return 1;
}
```

Both `mojo_read_type_tag` (`:4278`) and `mojo_read_type_tag_safe`
(`:4300`) use it.

`runtime/fire_runtime.c:522` — the wrong one:

```c
int mojo_boxed_is_str(int64_t v) {
    return v > 65536 && !mojo_is_registered_list(v);
}
```

`65536` is **32768x below** the 2 GiB floor its own neighbour enforces.
Everything between 64 KiB and 2 GiB is classified "definitely a string
pointer" by `mojo_boxed_is_str` and "definitely not a pointer" by
`_mojo_tagged_addr_ok`.

### The faulting value

Measured faulting tag: **`0x6f6490ed`** = 1,868,861,677 = **1.741 GiB**.

- `> 65536` → `mojo_boxed_is_str` says **yes, a string pointer**
- `< 0x80000000` (2 GiB) → `_mojo_tagged_addr_ok` would **reject** it
- fits in 31 bits → it is exactly a **struct type-tag**, the
  `zlib.crc32(name) & 0x7fffffff` shape that `_mojo_tagged_addr_ok`'s own
  comment says it exists to reject

So a 31-bit type-tag is misread as a heap pointer and dereferenced.

### The call chain

```
mojo/middle/exprtypes.py:61   _WALK_FIELD_NAMES_CACHE.get(type(node))
  -> runtime/fire_runtime.c:6238  mojo_cstr_or_int_str(int64_t v)
  -> runtime/fire_runtime.c:522   mojo_boxed_is_str(v)          // v > 65536  => TRUE
  -> runtime/fire_runtime.c:6239  return (char *)(intptr_t)v;   // deref 0x6f6490ed
  -> SIGSEGV
```

Other `mojo_boxed_is_str` call sites, all reachable the same way:
`fire_runtime.c:4525`, `:6307`, `:6309`.

## 4. Why it only crashes self-hosted

Under CPython, `type(node)` returns a **real class object** — a genuine
heap address above 2 GiB. `mojo_boxed_is_str` is accidentally correct,
because the value it is handed really is a pointer.

Self-hosted, `type(node)` yields a **31-bit struct type-tag**, not a class
object. The 16-bit test accepts it; the dereference kills the process.

This is a **known, already-documented bug class** on the Python side.
`mojo/backend_gimple/emit_funcs.py:727` says so outright:

> Deliberately an isinstance chain, NOT a `type(_val)`-keyed dict lookup:
> confirmed by hand that `type()` yields an unreliable
> (non-uniquely-identifying) tag self-hosted — the exact same bug class
> already found and fixed for `_WALK_FIELD_NAMES_CACHE` in
> gimple_exprtypes.py.

The Python-side fix (swap the `type()`-keyed dict lookup for an isinstance
chain) does **not** help here: the surviving instance of this bug class
is in the **C runtime**, where there is no isinstance chain to swap. That
is why `mojoc` still dies while `python3 fire.py` is fine.

## 5. Suggested fix (untried — verify before trusting)

Make `mojo_boxed_is_str` use the same predicate as its neighbour, so one
runtime has one definition of "this int64_t is a real pointer":

```c
int mojo_boxed_is_str(int64_t v) {
    return _mojo_tagged_addr_ok(v) && !mojo_is_registered_list(v);
}
```

Note `_mojo_tagged_addr_ok` is `static` and defined at `:4243`, *after*
`mojo_boxed_is_str` at `:522` — so this needs a forward declaration or a
reorder, not just a one-token edit. The `malloc_usable_size` arm is
strictly stronger than what a "is it a string" test needs; if it proves
too strict for boxed strings, the minimum correct change is to reject the
31-bit tag range, i.e. raise the floor from `65536` to `0x80000000` and
keep the alignment check.

Careful: `mojo_boxed_is_str` is a *permissive discriminator* used to
recover a `char *` from an untyped `int64_t` (see the
`mojo_cstr_or_int_str` docstring at `:6225` — the
`f = lambda k: d[k]; f("a")` case). Widening the rejection is
crash-safety-positive and can only turn a wrong answer into a right one,
but it will change behaviour on any value in 64 KiB..2 GiB that was
previously "worked by accident". Expect fallout in the A/B corpus and in
`stdlib`; measure rather than assume.

## 6. Where to look first

| what | where |
|---|---|
| the bad predicate | `runtime/fire_runtime.c:522` |
| the good predicate | `runtime/fire_runtime.c:4243` |
| the dereference that dies | `runtime/fire_runtime.c:6239` |
| the value entering it | `mojo/middle/exprtypes.py:61` |
| the same bug class, Python side, already fixed | `mojo/backend_gimple/emit_funcs.py:727` |
| existing history on this crash | `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`, entry dated 2026-09-27 |
| NOT the same bug | `bugs/CODEGEN_bootstrap_resource_blowup.md` — that is a SIGTRAP (133) on the large transitive dump, intermittent. This is SIGSEGV (139), two-line input, 100% reproducible. Different signal, trigger, and reproducibility. |

## 7. Debugging notes

- Under lldb, the faulting key reads `0x6f6490ed` and the frame above it
  is `mojo_cstr_or_int_str`. That value being *below 2 GiB but above
  64 KiB* is the whole bug in one number.
- The crash is **silent by construction**: `mojoc --dump-full` produces no
  stderr, so a bisect has to be driven by exit status, not by log text.
- The segfault masks everything behind the first AST walk. Once it is
  fixed, expect a fresh wave of newly-reachable failures across
  `ab-native`, `native-dumpfull` and `bootstrap-stage2-dumps` — these were
  never exercised, because the process died before reaching them.
