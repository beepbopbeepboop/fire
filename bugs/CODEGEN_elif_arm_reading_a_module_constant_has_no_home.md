# CODEGEN: a module-level constant read on the right of an assignment, or inside an `elif` arm, is refused as having "no home"

> **BOTH HALVES FIXED**, and the second half's cause was neither of the two
> this file originally blamed. The assignment half's real cause was upstream of
> the emitter (`formal/build.py`'s `_apply_module_constant_sites`); the `elif`
> half's is the same walk, one position over. Both were walk bugs, not emitter
> bugs. Read "The correction" below before the original text.

## Status (2026-09-30 — FIXED. Both halves closed; the emitter was never involved)

Measured on this tree, arm64 and x86-64, after the fix: every row of the
original table builds, and the `elif` rows **return 2** on both architectures.

The assignment half (`y = K`, `x: Int = K`, `h.a = K`, `x = K()`) was fixed
separately and is on `round8-merged` / `work/merge2-formal`, not on the branch
this was fixed on — see the integrator note at the bottom.

## The correction: `IfStmt.elifs` is a list of TUPLES, and the walk handled lists

The original diagnosis says an `elif` condition is "emitted in a different
place from the `if`'s, and that place has no folded-constant case", and blames
the phi/web slot the arm's condition result would need. The emitter is
innocent. `_emit_if` (formal/arm64_codegen.py:1601) builds one flat chain of
`(condition, body)` pairs and calls the *same* `_emit_branch_unless(cond, fail)`
for every arm, so there is no per-arm emission path that could lack a case.

The bug is one level up, in the substitution, and it is a data-shape accident:

> `IfStmt.elifs` is `[(condition, body), …]` — a list of two-tuples.

`_apply_module_constant_sites` (the module-constant walk) had

```python
if isinstance(node, list):
    …rewrite each element in place…
    return node
…
for name in node.__dataclass_fields__:
    setattr(node, name, _apply(…) if isinstance(child, list) else _rewrite_child(child, …))
```

A list was descended into; a **tuple was not**. So for `stmt.elifs` — a list —
the list branch ran, handed each `(condition, body)` pair to
`_apply_module_constant_sites`, and the pair matched neither `list` nor
`AssignStmt`, so the walk fell through to the `__dataclass_fields__` loop, found
none on a tuple, and returned having done nothing. The `elif` condition was
never visited.

The two other walks over this tree already knew: `strip_body`
(formal/build.py:424) and `walk_body` (formal/build.py:594) each spell out the
`(c[0], c[1], *c[2:])` unpacking in full. So the shape was known to the file and
unknown to one function in it, which is the whole mechanism.

Direct evidence, from the AST after `_prepare_functions` on the reproducer:

```text
IfStmt BinaryOp(op='==', left=IdentExpr(name='x'), right=IntLiteral(value=0))
      ← the `if` arm: K → 0, substituted
      elifs= [(BinaryOp(op='==', left=IdentExpr(name='x'),
                        right=IdentExpr(name='K')),   ← the `elif` arm: still K
               [ReturnStmt(...)])]
```

The `K` that survived is what the emitter then reported as having no home.

## The fix

Both substitution walks descend into a tuple, and a tuple — which has no
assignable slots — is REBUILT and returned rather than mutated:

* `_apply_module_constant_sites` (module constants) and `_rewrite_child`,
* `_apply_constant_sites` (class-level constants), which is the *second* walk
  with the identical one-position gap: `if p.B == 1:` was substituted and
  `elif p.B == 1:` was not, so `S.NAME` in an `elif` arm was refused with the
  same message for the same reason.

`_apply_module_constant_sites` rewrites a child's own slots in place and returns
`None` for anything that is not itself a list or a tuple, so the list branch
puts the ORIGINAL child back unless the recursion handed back a rebuilt
container. That distinction is load-bearing and is why the line reads the way
it does: using the return value unconditionally puts `None` in the list, and the
build then fails with `unsupported statement NoneType` — measured, on the way
to this fix.

## The original report (2026-09-29), kept as written

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
| `y = K` | **FIXED (assignment half)** |
| `elif x == K:` | **FIXED 2026-09-30 (this branch), returns 2 on both architectures** |

`x = K()` — a CALL whose callee is the constant — built too, and was wrong in
the other direction: the callee was replaced by a literal, so the image called
the number 7. Fixed with the same one line as the assignment half. It is listed
here because it was the same defect in the same walk and this file's table is
the only place in the tree that enumerates what that walk does and does not
cover.

Also refused, and the same shape: `J = K` at module level, which gets a
*different* message — `'J' is bound at module level, and this path has no
module-global storage for …` — so a module-level constant can be read but not
re-bound through another module-level name.

Measured identically on `--backend x86_64`, so this is in the shared
allocation path and not in one emitter. (Re-measured 2026-09-30: the two
architectures agree on every row above, before and after.)

## Why it happens — superseded, kept for the shape of the reasoning

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

Every clause of that is wrong about the cause, and the reasoning error is worth
naming because it is easy to repeat: it starts from the message
("has no home" → the allocator) rather than from the question the message is
supposed to answer (why did a name that IS placed reach the emitter as a bare
`IdentExpr`?). The message was accurate about its own situation — there was
genuinely no home for `K` — and wrong about the file, because `K` should never
have been there.

## What a fix has to preserve

The refusal must stay a refusal. The alternative — letting the emitter read the
name with no home — is exactly the silent-wrong-answer failure this path was
built to prevent, and the message says so ("one program returned 10 on arm64
and 0 on x86-64 where the source says 5"). So the fix is to give the two shapes
a home, not to relax the check.

The fix that landed does exactly that and keeps the check: nothing in
`check_module_symbols` or `unresolved_name_refusal` was touched, and
`elif_arm_reads_a_module_constant` /
`elif_arm_reads_a_class_constant` in `test_formal_run.py` are new rows that
BUILD and return the right number, next to `int_class_constant_comparison_still_builds`
and `elif_chain_of_literals_is_unchanged`, which are the guards that would catch
an over-correction in the other direction.

## Measured impact on this repository

`formal/hostmods/ast.mojo` is written around this: it passes every constant it
needs as an *argument* (`_put(out, 0, NAME_K)` rather than binding
`NAME_K` to a local) and uses sequential `if`s with early returns instead of
`elif`. Both are noted at the functions that do it, with this file's name, so a
reader does not have to rediscover why the code looks like that.

**That workaround is no longer necessary for the `elif` half**, and the file
still carries the comment. Rewriting it to use `elif` is a separate change with
its own verification (it is a host module, so it is exercised through
`test_ast_formal.py` rather than by a build), and it is not this fix's business.
The next person to touch `ast.mojo` should know the note is now half-stale.

## Integrator note

The assignment half's one-line fix
(`formal/build.py`, `_apply_module_constant_sites`, the
`AssignStmt`/`AugAssignStmt`/`VarDecl` branch: `node.value = _rewrite_child(…)`
in place of the in-place walk) is **on `round8-merged` and
`work/merge2-formal`, not on master**. This branch was forked from master, so
it does not have it, and this fix did not re-land it — that would be another
worker's commit duplicated, and the two touch adjacent lines. The change made
here is in the `list`/`tuple` branch above that one, in `_rewrite_child`, and
in `_apply_constant_sites`; `git merge` should resolve them independently, but
the two hunks are within a few lines of each other and a conflict is possible.
Resolution, if there is one, is: keep BOTH — the `node.value = _rewrite_child(…)`
assignment AND the tuple descent.
