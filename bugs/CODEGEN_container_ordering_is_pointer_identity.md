# CODEGEN: `<` / `>` / `<=` / `>=` between two containers is a POINTER comparison

> **Sibling doc — DELETE IT.** `bugs/CODEGEN_container_eq_is_pointer_identity.md`
> is fixed by `test_container_equality.py`'s branch (`work/container-eq`, 2026-09-30):
> `==` / `!=` between containers is now Python value equality on the compiled path,
> on all three lowering routes, diffed against CPython case by case. That doc lands
> with `merge2-compiled` / `round8-merged`, which is AFTER the branch that fixes it,
> so a plain `git rm` on the fixing branch is a no-op and the open doc would survive
> the merge. Whoever integrates should `git rm` it in the same commit as the merge.
> Kept here rather than in a scratch file because this is the one place a reader of
> an ordering bug will look for the state of its sibling.
>
> Also read, and deliberately NOT touched: `bugs/CODEGEN_in_dispatch_int_has_no_dict_branch.md`
> (`x in <dict>` on the erased int view has no dict branch in `mojo_in_dispatch_int`).
> Same erased-container family, one line of runtime, but a different question
> (`in`, not `==`) and outside the claim this work held.

## Status (2026-09-30 — OPEN, measured on CPython 3.14.7; sibling of the `==`/`!=` bug this branch fixed)

`a < b` between two containers lowers to the same raw C pointer comparison
`a == b` used to lower to, so the answer is decided by heap addresses. Unlike
`==`, this is no longer unanswerable: **this project's CPython (3.14.7)
implements ordering for lists and sets**, so there is a correct answer to give
and the compiler gives the wrong one silently.

Found while fixing `==`/`!=` (bugs/CODEGEN_container_eq_is_pointer_identity.md,
now fixed on this branch). The fix there deliberately stopped at `==`/`!=` —
ordering is a separate lowering, not a flag on the value-equality predicates,
because the answer is a three-way-ish comparison and the runtime needs the
elements, not just equality.

## What was run, and what it showed

```python
def main() -> Int:
    a = [1, 2]
    b = [1, 3]
    c = [1]
    s1 = {1, 2}
    s2 = {1, 3}
    print(a < b)
    print(a > b)
    print(a <= c)
    print(s1 < s2)
    print(s1 > s2)
```

CPython 3.14.7 (`python3 -c ...`, same text) prints:

```
True
False
False
False
False
```

`test_container_equality.py`'s build-and-run harness on the same source
(`compile_to_gimple` -> `gcc -fgimple` + `runtime/fire_runtime.c` -> execute)
prints:

```
False        <-- a < b  should be True
True         <-- a > b  should be False
False
False
True         <-- s1 > s2 should be False
```

Four of the five differ, all exit 0, no diagnostic. So the compiled path
inverts `<` and `>` on containers and gets `s1 > s2` wrong while agreeing on
the two `<=`/`<` cases only by coincidence of the heap layout.

`{'a': 1} < {'b': 2}` is a genuine `TypeError` even on 3.14, so a dict is the
one container kind with no correct answer to give — it needs the honest refusal
the rest of this backend gives for what it cannot lower, not a comparison.

## Why it is silent

Identically to the `==` case and for the same reason: the answer is
*plausible*. Two containers' relative addresses are fixed within one run, so
`a < b` gives a stable answer; it is simply the wrong one, and nothing between
the lowering and the program's output complains.

## Exact next step

In `mojo/backend_gimple/emit_exprs.py`'s `_lower_binary_tail`, next to the new
`if op in ('==', '!=')` container block:

* `<`, `>`, `<=` for a list: `mojo_list_cmp(MojoList *, MojoList *, int ea, int eb)`
  returning the three-way answer, folded to the `_Bool` the operator wants.
  CPython's rule for lists is lexicographic, with a SHORTER prefix ordering
  first (`[1] < [1, 2]`), and a nested element that is itself a container
  recurses through `mojo_value_eq`'s registry resolution.
* `<`, `>` for a set: a proper subset test, both directions for `>` — NOT the
  lexicographic rule lists use, and not the `mojo_set_difference` emptiness
  shortcut without checking the other side (`s1 > s2` is False for equal-size
  proper subsets of each other, which is exactly the case above that fails).
* `<=`, `>=`: `==` OR the strict form, reusing the predicates this branch
  added rather than re-deriving them.
* a dict operand, and any pair of different kinds: raise/return a refusal, the
  honest answer.

The element codes and the per-side structure are already in place
(`_eq_elem_code`, `MOJO_EQ_*` in `runtime/fire_runtime.h`); the missing half
is the runtime's three-way element comparison, not the codegen's evidence for
what an element is.

Test beside `test_container_equality.py`, with the same build-run-and-diff
harness and the same five lines — that harness is what found this, and it is
what will tell a fix from a guess.
