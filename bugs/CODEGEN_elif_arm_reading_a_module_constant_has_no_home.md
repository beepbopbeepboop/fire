# CODEGEN: a module-level constant read on the right of an assignment, or inside an `elif` arm, is refused as having "no home"

> **HALF FIXED.** The assignment half is closed and the `elif` half is not. The
> original diagnosis was wrong about which half was which; see Status below for
> what actually caused the assignment half and where the fix went.

## Status (2026-09-30 — HALF FIXED. The assignment half is closed; the `elif` half is OPEN)

**The assignment half landed, and it was a different bug from the one described
below.** `y = K` was not refused for the reason this file gives — the doc says
an assignment's right-hand side "first wants a *destination* for the value",
which is true of the EMITTER and was never where the refusal came from. It came
from `formal/build.py`'s `_apply_module_constant_sites`, which rewrites IN PLACE
and returns `None` while `_rewrite_child` is the one that RETURNS a
replacement. Every position that needed a replacement went through
`_rewrite_child` (a list element in the list branch, any other single child in
the dataclass-fields branch) — except the `AssignStmt` / `AugAssignStmt` /
`VarDecl` branch, which called the in-place walk directly on the value. A value
that IS the constant is a bare `IdentExpr`, whose fields are `name`, `line` and
`col` and therefore no child slots to rewrite, so it was walked straight through
and the name was left in place. The substitution then never reached the
emitter, which is why the emitter's message was the one reported: the emitter
was refusing a name that the build was supposed to have already replaced.

The fix is one line — that branch now assigns `node.value = _rewrite_child(...)`
— and it closes the second shape the same walk mishandled, which this file did
not know about: a CALL whose callee is the constant, `x = K()`. The in-place
walk had no callee guard either, so the callee was replaced by a literal, i.e. a
call to the number 7. Both are covered by two cases added to
`test_formal_globals.py` (`read_global_as_an_assignment_value`,
`read_global_into_a_field_store`), each run through the interpreter and both
images; the field-store one is the shape ordinary struct code takes, which is
why the uncovered position was reachable without writing anything unusual.

**What remains OPEN is the `elif` arm**, unchanged and re-verified on this tree
after the fix above: `elif x == K` is still refused with the same message on
both architectures. That half really is the emitter-side problem this file
describes — a saved condition value with no folded-constant case — and it is
untouched by the substitution fix, which never reaches it because the name is
not in a position the rewriter visits.

Everything below is the ORIGINAL report of 2026-09-29, kept as written. Its
reproducer table is still accurate except for the two rows marked fixed above
(`y = K` now builds and prints 7), and its "Why it happens" section should now
be read as describing the `elif` half only — the assignment half's real cause
was upstream of the emitter entirely.

---

## Original report (2026-09-29 — OPEN, measured on arm64 and x86-64; the refusal is loud, never a wrong answer)

A module-level constant is folded into the image, and most reads of one are
fine. Two shapes are not: a read as the **direct right-hand side of an
assignment**, and a read inside an **`elif` arm**. Both are refused with

```text
build: f: 'K' has no home: the register allocator collected no home for it, so
the emitter and the allocation walk disagree about this function's locals. …
```

which is the right *kind* of message — a refusal rather than a read out of
whatever register the allocator left behind — but it refuses ordinary code, and
the same read in a neighbouring position is accepted, so the rule is not
something a caller can write around.

## Reproducers (each is a whole program; `python3 fire.py build --formal --no-prove`)

Refused:

```python
K = 7

def main():
    y = K          # 'K' has no home
    print(y)
```

```python
K = 7

def f(x):
    if x == 0:
        return 1
    elif x == K:   # 'K' has no home
        return 2
    return 0

def main():
    print(f(7))
```

Accepted, on the same tree and the same build — which is what makes this a
defect rather than a policy:

| program | result |
|---|---|
| `print(K)` | builds |
| `def f(): return K` | builds |
| `if x == K:` (an `if` arm) | builds |
| `var y = [K, K]` (a list element) | builds |
| `elif x == 7:` (a literal, in an `elif`) | builds |
| `K = 3` inside a function (a local shadowing the name) | builds |
| `y = K` | **refused — FIXED 2026-09-30**, builds and prints 7 |
| `elif x == K:` | **refused — still open** |

`x = K()` — a CALL whose callee is the constant — built too, and was wrong in
the other direction: the callee was replaced by a literal, so the image called
the number 7. Fixed 2026-09-30 with the same one line. It is listed here
because it was the same defect in the same walk and this file's table is the
only place in the tree that enumerates what that walk does and does not cover.

Also refused, and the same shape: `J = K` at module level, which gets a
*different* message — `'J' is bound at module level, and this path has no
module-global storage for …` — so a module-level constant can be read but not
re-bound through another module-level name.

Measured identically on `--backend x86_64`, so this is in the shared
allocation path and not in one emitter.

## Why it happens

`formal/arm64_codegen.py` places a name in a register or spill slot allocated
for the function being emitted, in a receiver field's frame, or in a
module-level constant the build folded. The "module-level constant the build
folded" case is what the two accepted shapes use: `print(K)` and `if x == K`
read the folded value directly, without materialising it as a local first. An
assignment's right-hand side and an `elif` arm's condition both go through a
path that first wants a *destination* for the value — the assignment's target
slot, or the phi/web slot the arm's condition result would need — and the
folded constant is not in that destination's home set, so the allocation walk
collects no home for it and the build refuses.

The `elif`-only half is the sharper one, because the `if` arm with the same
expression is accepted: an `elif` is lowered as a branch on a *saved* condition
value, so its condition is emitted in a different place from the `if`'s, and
that place has no folded-constant case.

## What a fix has to preserve

The refusal must stay a refusal. The alternative — letting the emitter read the
name with no home — is exactly the silent-wrong-answer failure this path was
built to prevent, and the message says so ("one program returned 10 on arm64
and 0 on x86-64 where the source says 5"). So the fix is to give the two shapes
a home, not to relax the check: either let an assignment's right-hand side be
emitted from the folded constant in place, or teach the allocation walk that a
module-level constant can back a saved condition value.

## Measured impact on this repository

`formal/hostmods/ast.mojo` is written around this: it passes every constant it
needs as an *argument* (`_put(out, 0, NAME_K)` rather than binding
`NAME_K` to a local) and uses sequential `if`s with early returns instead of
`elif`. Both are noted at the functions that do it, with the file name here, so
a reader does not have to rediscover why the code looks like that.
