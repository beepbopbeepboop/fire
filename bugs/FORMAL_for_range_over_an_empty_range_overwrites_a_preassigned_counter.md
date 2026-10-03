# FORMAL_for_range_over_an_empty_range_overwrites_a_preassigned_counter

**Area:** FORMAL, both backends — the for-range loop head in
`formal/arm64_codegen.py`'s and `formal/x86_64_codegen.py`'s `_emit_loop`.
**Status: the ONE-PAST case is FIXED (the counter now leaves at the last value
CPython bound); this is the remaining half, and it is a rarer spelling of the
same rule.**

Found 2026-10-03 on `work/formal14-fuzz-arm64` by `tools/formal_fuzz.py`, whose
seed 1 reduced to a four-line program; the fix it produced is
`both_arch_for_range_*` in `test_formal_run.py`.

## What is fixed, and what is not

The loop tests the counter before it advances it, so on exhaustion it arrives
one past the last value the body saw. Fixed: the loop head now tests and
branches to the body, the counter is advanced at the bottom, and the exit path
walks the counter back by the step. Every row of
`both_arch_for_range_leaves_the_counter_at_the_last_value_it_bound` and its eight
neighbours passes on both architectures.

**This is the case that fix deliberately does not cover**, and the reason is in
the shape of the fix: the head test is separate from the loop-back test so that
an EMPTY range leaves the counter at its initial value — which is what CPython
does when the counter was already bound — and it is that head test which stores
`start` into the counter *before* testing it. CPython's `for` binds the target
only when the iteration produces a value, so for a range that yields nothing the
name is never assigned and a prior value survives.

## The reproducer

```mojo
def main(n):
    i = 7
    for i in range(0, 0):
        x = 1
    print(i)
    return 0
```

| | |
|---|---|
| CPython 3.14 | `7` |
| arm64 | **`0`** |
| x86-64 | **`0`** |

Builds, runs, exits 0. Measured 2026-10-03 with
`python3 tools/memslot.py --gb 8 --label probe -- python3 fire.py build --formal
--no-prove -o .tmp/x .tmp/probe/empty.mojo` and the same with
`--backend=x86_64`; the eight `both_arch_for_range_*` rows in `test_formal_run.py`
are the guard that the fixed half stays fixed.

A range that yields nothing also reaches this through a variable bound:
`for i in range(0, k)` with `k <= 0` at run time, which is the shape that
matters — the emptiness is a run-time fact here and the store happens
unconditionally.

## The next step, precisely

The head test does not have to read the counter to compare against the bound.
Emit the FIRST test on `start_val` itself, and put the counter's store after it:

```
   cmp start_val, end_val ; j<holds> body_init ; j false
body_init: i = start_val
body:     …
step:     i += step ; cmp i, end_val ; j<holds> body ; i -= step ; j false
false:    [else body]
end:
```

An empty range then never reaches the store, which is Python's rule. The
catch, and it is the reason this was not done in the same commit: `start_val` is
evaluated twice on that path, so the substitution is only sound when `start_val`
has no side effects — an `IntLiteral`, a negated literal, or a plain name. For
anything else (a call in the first argument of `range`) keep today's order. So
the change is one purity test on `start_val`, keyed by the same question
`formal/model.py` already answers for other constructs — check for an existing
predicate before writing a second one — and two labels in `_emit_loop` on both
backends. The instruction vocabulary is unchanged (`CMP`, `B.cond`/`Jcc`,
`MOV`/`STR`), so neither Lean model needs a new step.

The alternative, which is one instruction shorter and wrong: subtract on every
exit including the empty one. `i = 7` before `for i in range(0, 0)` would then
print `7 - step`.