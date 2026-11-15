# CODEGEN: two same-name free functions in one module are neither emitted nor callable

Parent: `bugs/hard/CODEGEN_stdlib_dylib_lazy_undefined_refs.md` (its
`## Replan (2026-11-15)` table is the measured state). This is part 8.

## Goal

A module that declares two free functions with the same name must emit a
definition for each, under its own overload-mangled symbol, and a call must
name one of them — inside the module and from another module. Today neither is
emitted and the call becomes a bare, unqualified, suffix-less stub.

## Evidence (measured 2026-11-15, this tree)

Synthetic module with `def pick(x: Int)` and `def pick(x: Bool)` plus
`def use(x: Int): return pick(x)`: the generated C has NO
`p8_pick_pick_<hash>` definition at all, only

    __attribute__((weak)) int64_t pick (...)
    { mojo_print ((char *)"pick: unavailable in compiled mode"); return 0; }
    _t8 = pick (x);

The same shape is live in the stdlib (all four have exactly two overloads):

| defining module | caller | reference seen today |
|---|---|---|
| `std/bit/mask.mojo` (`splat`) | `std/collections/string/string_span.mojo` | `extern int64_t std_bit_mask_splat (void);` |
| `std/memory/memory.mojo` (`_free`) | `std/memory/pointer.mojo` | `extern int64_t std_memory_memory__free (void);` |
| `std/memory/memory.mojo` (`unsafe_memset_zero`) | `std/memory/maybe_uninit.mojo` | `extern int64_t std_memory_memory_unsafe_memset_zero (void);` |
| `std/collections/string/_parsing_numbers/parsing_integers.mojo` (`to_integer`) | `.../parsing_floats.mojo` | `..._to_integer_fa3cf4` — and `parsing_integers.mojo`'s C contains no `to_integer` at all |

The `(void)` in the first three is the imported-signature fallback: with two
candidates the text scan cannot pick a signature, so it emits the bare name
with no arity. `to_integer` has no `(void)` because its caller's signature was
resolvable; only the definition is missing.

## Work

1. The definition pass must not key free functions by bare name. Register each
   overload with its own signature key and emit each under `_func_csym`'s
   name. `to_integer`'s two overloads (`StringSlice[_]` and
   `Array[Byte, CONTAINER_SIZE]`) are the proof that the second definition is
   currently unreachable even when the first is never called.
2. The call-site resolution must pick an overload by arity and argument types
   and emit the corresponding qualified, suffixed extern — not the `(void)`
   fallback. This also fixes the three `(void)` references above.
3. A fix that INLINES a call to an `@inline(.always)` function at the call site
   is acceptable for those three and leaves no reference at all; it does not
   make `to_integer` (not inline) resolvable, so the definition-pass half is
   still required.
4. Do not special-case a function name or module: the synthetic probe must go
   green from the same change as the stdlib table.

## Acceptance

- The synthetic two-overload module defines both `pick` overloads and its call
  names one of them.
- A two-module dylib (defining module + caller) leaves no unresolved `_std_`
  reference in each of the four rows above.
- Single-definition modules are unchanged (all of `test_gimple.py`'s free
  function cases keep their symbols).

## Done when

`python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p8_overload` exits 0.
It compiles the synthetic module (1 s), then builds four two-module dylibs
with `build_stdlib_dylib.build` and asserts `nm -u` has no unresolved member
of each family (about 20 s total, all under the probe's `tools/memslot.py
--gb 8` run).
