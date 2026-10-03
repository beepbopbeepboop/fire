# FORMAL_a_comprehension_over_a_spliced_literal_exits_1: `[v for v in [*a]]` stops at the capacity guard on BOTH backends

**Area:** FORMAL / codegen (shared — arm64 and x86-64 alike). Found 2026-10-03
while landing the x86-64 half of the dynamic list splat
(`bugs/FORMAL_x86_64_dynamic_list_splat_is_refused.md`, deleted by that commit),
adding a case that put a comprehension and a splice loop in one expression.

**Status: OPEN, pre-existing, and NOT FIXED here — it is not a splat problem.**

## What I ran

```
$ cat > .tmp/sp/comp.mojo
    def main():
        var a = [3, 4, 5]
        var c = [v * 10 for v in [*a]]
        printf("n=%d %d %d", len(c), c[0], c[2])
        return 0

$ … --backend=arm64  … && ./out ; echo $?     →  (no output)  1
$ … --backend=x86_64 … && ./out ; echo $?     →  (no output)  1
$ python3 comp.mojo                           →  n=3 30 50     0
```

The narrowing, all four builds measured one at a time:

| program | arm64 | x86-64 |
|---|---|---|
| `var d = [*a]; [v * 10 for v in d]` | `n=3 30 50` | `n=3 30 50` |
| `var c = [*a]; len(c)` | `n=3` | `n=3` |
| `var c = [v * 10 for v in a]` | `n=3 30 50` | `n=3 30 50` |
| `var c = [v for v in [*a]]` | **exit 1** | **exit 1** |

So it is neither the comprehension, nor the splice, nor the two in sequence —
it is the comprehension's iterable being a **literal**, which the
comprehension evaluates inside its own reservation.

Nothing is printed and the status is 1, which on this path is the capacity
guard's exit (`_compr_append_elem` / `_emit_call_exit`), not a subscript bounds
miss and not a refusal.

## Why it happens

`_emit_comprehension` reserves the result blob, then `_emit_compr_gen`
evaluates `gen.iterable` — and for `[*a]` that evaluation calls
`_emit_list_star`, which reserves its **own** blob out of the same frame budget,
8 slots for the dynamic operand (`model.dynamic_splat_capacity`). The
comprehension's capacity is `_compr_cap(expr)`, computed from the source before
any of that happens, so the sum of the two reservations is not what either of
them checked. With a comprehension cap of a handful of slots the append reaches
the guard on the first or second element.

The same shape is presumably why the comprehension's cap is derived from
source at all: the iterable is a *name* in every corpus case, so nothing
exercised the literal.

## The exact next step

1. **Decide the budget question first, and write it down.** Two reservations
   from one expression is a frame-budget fact, and the three candidate answers
   are all defensible: refuse a comprehension whose iterable is a container
   literal (`model.frame_blob_refusal` has the vocabulary), make the
   comprehension's cap account for the iterable's own reservation, or make the
   iterable's literal share the comprehension's reservation. The middle one is
   a fix that needs the second cap to be computed after the first reservation,
   which is a layout-order change in `_emit_comprehension`.
2. **Then the exit test has teeth.** `test_formal_list_splat.py` deliberately
   does NOT cover this shape — its `a_comprehension_over_a_spliced_result` case
   is written over a *name* holding a spliced result, and says so in a comment
   pointing here. That is the right call while this is open and the wrong call
   the moment it is fixed, because the differential harness is already
   everywhere else. Add `[v for v in [*a]]` to
   `test_formal_list_splat.py` as a case when step 1 lands.
3. Do **not** fix it by widening `DYNAMIC_SPLAT_SLOTS` or the comprehension's
   cap. The guard is the only thing standing between a program and a frame
   write past its blob, and "the test stopped overflowing" is not evidence that
   a reservation is now right.

## Scope

Neither backend is wrong here in the *wrong-answer* direction — both stop
loudly — which is why this sat unnoticed while the construct was new. It is not
caused by the x86-64 splice lowering and it does not affect the two backends
differently; it reproduces from a clean `master` for arm64.