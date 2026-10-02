# TEST: `a_mutated_module_global_is_refused` asserts a refusal the module no longer owes

**Area:** TEST (one row of `test_formal_run.py`). **Status: OPEN — a stale
expectation, measured on `master` as well as on the branch that found it, so it
is not a regression from anything in flight.** Filed rather than fixed, because
the behaviour it asserts about belongs to the `bug:FORMAL_module_state_no_storage`
claim and the decision of whether a `__DATA` slot is enough for a module-level
name this program WRITES is not mine to reverse.

## What I ran

```
$ python3 test_formal_run.py a_mutated_module_global_is_refused
  FAIL  a_mutated_module_global_is_refused: --backend=arm64 BUILT a construct
        that has no representation (expected a refusal naming 'G is declared
        `global` in bump() and assigned there')
```

The program is the row's own source:

```mojo
G = 5
def bump():
    global G
    G = G + 1
    return G
def rd():
    return G
def main(n):
    return bump() + rd()
```

## What I see

It **builds, links and runs**, and prints nothing and exits **12** — which is
CPython's answer (`G` becomes 6, so `6 + 6`). The same on `master`: extracted
with `git archive master | tar -x -C .tmp/pre` and built there, byte-identical
behaviour, and the row fails there too.

## Why it is stale, which is a fact and not an opinion

`formal/build.py`'s `_collect_shadowed_global_reads` still computes the finding
and still parks it, and `check_shadowed_global_reads` still raises it — but the
collector gates the finding on

```python
writable = declared_globals & assigned - set(M.module_slots() or ())
```

so a name that HAS a `__DATA` slot is not a finding. That gate is deliberate and
its own comment carries the measurement: "`formal-module-globals` landed the
slot, so refusing it now refuses a program this path computes exactly. Measured:
it was 6 of `test_formal_globals.py`'s 17 cases before this gate and 0 after,
and the image answers CPython (`G = 5` with `global G; G = G + 1` called twice,
read back after: 7)."

So the gate landed, `test_formal_globals.py` was updated with it, and this row in
`test_formal_run.py` was left behind. `model.mutated_module_global_refusal`'s
docstring still quotes the pre-slot measurement (10601485 and 5 on arm64), which
is now history rather than the current answer — worth knowing when reading it.

## The next step, for whoever owns the claim

**Decide the row, do not delete it.** Two consistent outcomes:

1. **The slot is the answer** (what the tree does today). Replace the
   `refuse:` expectation with the built program's own answer and make the row
   assert it: exit 12, which is CPython's. It becomes the `test_formal_run.py`
   half of the same fact `test_formal_globals.py` already pins, on the shape
   with a `return` of the global rather than a bare increment.
2. **A `global` WRITE is still not supported** and the gate is too wide. Then
   the gate is the bug, the row is right, and the fix is to narrow
   `writable` — with the sweep number for the narrowing, since the whole reason
   the gate is as wide as it is is the 6-of-17 measurement above.

Either way the row must stop being red, and the choice belongs to
`bug:FORMAL_module_state_no_storage`'s owner. **This is not filed as a
FORMAL_ bug on purpose**: the defect, if there is one, is in the gate, and
`FORMAL_module_state_no_storage.md` is where that belongs.

## Also measured on the same run, and NOT filed

`test_formal_run.py`'s four `byref_cross_module_*` rows fail the same way on
`master` and on this branch (a cross-module free function's frame-holder
parameter is refused by the callee-no-def ceiling rather than by the
cross-image contract sentence the rows expect). That area has docs and owners —
`bugs/FORMAL_cross_image_frame_contract_is_not_published_for_a_free_function.md`
and `FORMAL_frame_param_contract_is_published_empty.md` — so they are reported
here rather than duplicated.
