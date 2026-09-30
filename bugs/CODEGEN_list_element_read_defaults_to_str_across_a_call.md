# CODEGEN: a heterogeneous list bound from a CALL RESULT reads every element as a string — SIGSEGV on a float slot

Found 2026-09-30 while writing the regression test for the per-slot kinds
table (`CODEGEN_container_free_registry_dangling_entries.md`), on the way to
proving the fix. It is the MIRROR of
`CODEGEN_list_of_string_read_as_int_when_filled_in_a_callee.md` — that one is
a `List[String]` whose element reads back as an INT, this is an unannotated
`List` whose element reads back as a STRING — and it is not the same root
cause in the direction that matters, so it is filed separately rather than
folded in.

## Status (2026-09-30 — OPEN, reproduced on current master, NOT caused by the
kinds-table fix; the repro below segfaults identically with the pre-fix
`runtime/fire_runtime.c`)

## The bug

A list whose elements are of mixed types, built in a callee and bound to a
local in the caller, is read with `mojo_list_get_str` for EVERY element — so
a float slot's IEEE-754 bit pattern is handed to `strlen`:

```mojo
fn mixed(x: Float64, s: String) -> List:
    return [x, 1, s]

fn main():
    var a = mixed(2.5, "yy")
    var p = 0
    print(a[p])        # SIGSEGV
```

`a[0]` is 2.5's bit pattern, `0x4004000000000000`, which is not a mapped
address. `print` passes it to `mojo_print` and the process dies with SIGSEGV
(exit 139) after printing whatever came before it.

The generated C is the whole story — one call, no kinds probe, no box:

```c
_t5 = (int64_t) p;
_t6 = mojo_list_get_str (a, _t5);
mojo_print (_t6);
```

## Why it happens, as far as this investigation got

The callee's own body records the literal's per-slot kinds on the VALUE at
runtime (`mojo_list_set_kinds`, so the whole-result `repr` is right and
`a`'s row exists), and a whole-program scan of the callee can tell the call
site that the return is a heterogeneous list — that is what makes the
COMPUTED-index read on the list a `drop_one()` returns go through
`mojo_list_get_boxed` and print `9.5`. But the local `a` here is bound
directly from `mixed(...)`, and the element type the caller infers for it
falls back to `str`; there is no per-slot probe on that path at all.

Note what is NOT the cause: the kinds side table itself. Verified by
building the same generated C against the pre-fix runtime
(`git show HEAD:runtime/fire_runtime.c`) — identical SIGSEGV. And the whole
list's `repr` is correct in both builds, so the value is described properly;
only the element READ is mistyped.

## What was run

```
python3 .tmp/probe.py kt3.mojo            # compile_to_gimple + gcc -fgimple + run
```

(`kt3.mojo` is the three-line `mixed`/`a[p]` repro above; `probe.py` is a
throwaway peak-RSS harness. Both are in the session's `.tmp/`, not in the
tree.) A/B: `runtime/fire_runtime.c` at HEAD vs. with the kinds-table fix —
same crash, same output, both exit 139.

## Next step

`a`'s element type. The mechanism that marks a value as "may be boxed"
(`gen._maybe_kinds_vals` in `gimple_codegen.py`, consulted by
`emit_exprs`/`emit_calls`/`emit_loops` for `mojo_list_get_boxed`) is seeded
for a list LITERAL, where the codegen sees every element. A local bound from
a call never enters it, so the subscript lowering falls back to the local's
inferred element type — and an unannotated `List` infers to `str`. Either:

1. seed `_maybe_kinds_vals` for a call result whose whole-program callee scan
   says the returned list is heterogeneous (the same scan that already makes
   `drop_one()`'s result work — it is present, `gimple_codegen.py`'s
   return-ELEMENT-type inference, and its result is simply not consulted for
   this binding), or
2. make the fallback for an unknown element type fail CLOSED: read the slot
   through `mojo_list_get_boxed` and let the runtime decide, instead of
   committing to `str` and handing a float's bits to `strlen`.

(2) is the more robust of the two and is the same shape as the rule this
repo already states for the ownership predicates — an uncertain guess must
resolve to "ask the runtime", never to "dereference it" — but (1) is the
smaller change and would leave the `str` fallback in place for the cases it
does not cover.

While in there, the same lowering is what makes
`CODEGEN_list_of_string_read_as_int_when_filled_in_a_callee.md`'s repro read
a `String` slot as an int; both are one bug ("the element type of a list is
recorded where the list is built, and never travels with the value to the
subscript") seen from two ends, and fixing the read path for both is
probably less work than two directional fixes.
