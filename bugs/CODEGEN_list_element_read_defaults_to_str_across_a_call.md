# CODEGEN: a heterogeneous list bound from a CALL RESULT reads every element as a string — SIGSEGV on a float slot

Found 2026-09-30 while writing the regression test for the per-slot kinds
side table that same work repaired, on the way to proving that fix. It is the MIRROR of
`CODEGEN_list_of_string_read_as_int_when_filled_in_a_callee.md` — that one is
a `List[String]` whose element reads back as an INT, this is an unannotated
`List` whose element reads back as a STRING — and it is not the same root
cause in the direction that matters, so it is filed separately rather than
folded in.

## Status (2026-10-30 — the SIGSEGV is fixed and every statically indexed
## read is now exact; ONE read is still wrong and is named below)

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

Done — see "What landed" above for what was implemented and for the single
read (iteration, no compile-time index) that is still wrong and why it needs
a different mechanism.

## What landed (2026-10-30), and the one read that is still wrong

The doc's option (1) — "seed the mechanism for a call result whose
whole-program callee scan says the returned list is heterogeneous" — is what
was implemented, and it needed the scan to learn a second thing.

`_infer_return_maybe_kinds` is the pass that decides the cross-function half.
It recognised ONE producer of a kinds-carrying value, `struct.unpack` of a
mixed format, and not the other: a heterogeneous list LITERAL. So
`return [x, 1, s]` described itself perfectly while its own function was being
lowered and lost every word of it at the boundary. It now returns
`(maybe_kinds, slot_kinds)`:

* `maybe_kinds` joins the existing `_return_maybe_kinds` set, so the call site
  registers the result in `gen._maybe_kinds_vals` — the flag the subscript and
  iteration lowerings already consult. That is the fail-closed half the doc
  asked for as option (2): the read goes through `mojo_list_get_boxed`, which
  asks the runtime, instead of committing to `str` and handing a float's bits
  to `strlen`. **The SIGSEGV is gone.**
* `slot_kinds` is new (`gen._return_value_slot_kinds`) and is the per-INDEX
  half: the long-form kind of every slot of a returned heterogeneous literal,
  in the same spelling `gen._struct_slot_kinds` already carries for a
  `struct.unpack` result, seeded at the call site so every statically indexed
  reader picks its own accessor with no new site. `'str'` is a new kind name
  there (a `char *` slot is the raw word, so it reads through
  `mojo_list_get_str`), and it is what makes `a[2]` answer `yy` instead of the
  decimal of its own pointer.

The one remaining wrong read: **ITERATION**, where there is no compile-time
index to pick an accessor from.

    for v in a:
        print(v)

prints `2.5`, `1`, and then the decimal of the string slot's own pointer. The
boolean half reaches the loop body, the loop reads through `mojo_list_get_boxed`
— which is right for the numeric slot and, for a `char *` slot, returns the
raw word — and nothing downstream knows the word is a pointer. A statically
indexed read has a per-slot answer to consult; a loop variable does not.

Making it right is per-ELEMENT runtime typing in the loop body, and it is the
same project as
`bugs/CODEGEN_materialized_container_has_no_element_type.md` (a value whose
container KIND is a runtime fact has the same problem for its ELEMENT type).
Do them together; the shared piece is a runtime-dispatching element reader that
a consumer can ask per slot.

## Verified

```
python3 test_gimple.py            352 passed, 1 failed
    (the one failure is py_tokenize's ABI table, another worker's fix in flight —
     see the Status note at the end)
python3 .tmp/probe2.py <fixture>  single-TU and link-mode MATCH CPython for
    print(a[0]) / print(a[1]) / print(a[2]) / len(a)
```
