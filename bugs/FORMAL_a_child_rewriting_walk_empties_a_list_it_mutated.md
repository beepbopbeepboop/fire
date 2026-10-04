# a child-rewriting walk that mutates a list IN PLACE also returned it, so a replacement inside a nested list emptied it

**Area:** FORMAL (`formal/build.py`'s source-to-source rewrite walks — the
`pop.select` / dialect-arithmetic pass family). Found 2026-10-04 on
`work/formal19-4`, while landing items 1 and 3 of
`bugs/FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops.md`.

**Status: FIXED on the branch that found it** (`formal/build.py::
_rewrite_dialect_in` is the ONE walk for both dialect passes, with the correct
rule). Kept as a doc because the same shape exists twice more in the tree and a
reader who has seen the failure will not recognise it a third time.

## The bug

A walk over an AST that replaces children has to handle three shapes, and only
two of them can return a replacement:

  * a **single-attribute child** — replaced through `setattr`;
  * a **tuple** — not assignable, so one with a replaced element comes back as a
    LIST and the slot it was read from takes it;
  * a **list** — assignable, so it is mutated in place and the caller has nothing
    to do.

The shape that was written, in the two dialect walks:

```python
if isinstance(node, (list, tuple)):
    out = []
    changed = isinstance(node, tuple)
    for i, child in enumerate(node):
        repl = walk(child, ...)
        if repl is not None:
            changed = True                  # <-- true for a LIST too
        if isinstance(node, list):
            if repl is not None:
                node[i] = repl
        else:
            out.append(child if repl is None else repl)
    return out if changed else None         # <-- and `out` is [] for a list
```

`changed` is set from `repl is not None`, which happens for a list exactly as
often as for a tuple — and for a list `out` is never appended to, so the return
value is the EMPTY list. **A list that is itself an ELEMENT of another list has
its parent's `node[i] = repl` fire on that empty list**, and the elements are
gone.

`_fold_target_queries_in` — the third copy, and the oldest — has the correct
guard (`return out if (changed and isinstance(node, tuple)) else None`) and its
comment says why: "A tuple with nothing replaced returns None, which is what
keeps the common case … from rewriting the list it lives in." The author knew
about the list case and the two walks copied from it anyway.

## The measurement

`CallExpr.kwargs` is a list of `(name, value)` pairs, so a replacement that
lands in a keyword argument is in a list nested inside a list — the one place
this shape is reachable in the dialect walks.

```
$ cat .tmp/t9.mojo
struct Idx:
    var tag: Int
    var v: __mlir_type.index

def addit(self: Idx, rhs: Idx) -> Idx:
    return Idx(tag=0, v=__mlir_op.`index.add`(self.v, rhs.v))

def main() -> Int:
    var a = Idx(tag=1, v=-7)
    var b = Idx(tag=2, v=2)
    printf("%d\n", addit(a, b).v)
    return 0

$ python3 fire.py build --formal --no-prove -o .tmp/t9 .tmp/t9.mojo
  File "formal/build.py", line 2285, in _frame_argument_slots
    for kwname, value in (call.kwargs or []):
ValueError: not enough values to unpack (expected 2, got 0)
```

and the tree at the point of the raise:

```
kwargs = [['tag', IntLiteral(value=0, …)], []]
```

The same program with `v=self.v + rhs.v` in place of the dialect operation
builds and prints `-5`, so the fault is the rewrite and not the program.

**A crash rather than a wrong answer**, which is the better of the two outcomes
and is the only reason this was findable at all: an emptied `kwargs` list cannot
be mistaken for a computed value, it takes the build down.

## Why it was LATENT in `pop.select` and not found by its own suite

The select pass replaces exactly two shapes, and both are `CallExpr`s:
`x.__mlir_bool__()` and `__mlir_op.`pop.select`(c, a, b)`. The walk is
pre-order, so a select that is an ARGUMENT of another call is reached through
that callee's `args` — a dataclass field, whose result the caller discards, and
the in-place mutation is enough. So:

  * a replacement in `args` / `kwargs` / `attrs` was harmless;
  * a replacement in a list NESTED inside one of those was fatal.

`test_formal_mlir_precedence.py`'s select cases all put the select in a `return`
or in `printf`'s arguments, so nothing reached the fatal shape. The row that
reaches it now is `a_dialect_operation_lowers_inside_a_keyword_argument`, and
its own comment says what it is a regression pin for — a rewrite is exactly the
kind of change whose test ought to be written before the next one.

## The fix, and what is deliberately NOT folded in

`formal/build.py::_rewrite_dialect_in(node, rewrite, count)` is the one walk,
with the rule stated in its own docstring: **a list is mutated in place and never
returned.** `rewrite(child)` answers with a replacement, `None` to descend, or
`_KEEP_WHOLE` to leave the node and not descend — the third answer is what a
dialect template this build cannot answer needs, so the two passes do not each
grow their own.

`_fold_target_queries_in` is left as it is, deliberately: it already had the
correct list rule, and its per-shape template handling (an unanswerable template
keeps its shape WHOLE in list position but is descended into in field position)
is a decision about the dialect templates rather than about the walk. The shared
rule lives in the new walk so the next pass does not write a fourth copy.

## The next step, for whoever reads this next

The class is "a walk that mutates a container in place and also returns it".
`formal/` is the place to look; this file records two instances and one
third copy that is correct. A cheap census — every `changed = isinstance(node,
tuple)` in the tree, or every walk with both a `node[i] =` assignment and a
`return out` — is the instrument, and it does not exist.

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_mlir_precedence.py \
    a_dialect_operation_lowers_inside_a_keyword_argument
```

Reverse-applied (the old `return out if changed else None` put back in
`_rewrite_dialect_in`), **2 of the 28 cases fail and the other 26 pass**:

```
FAIL  a_dialect_arithmetic_lowers_when_its_operand_declares_a_word:
      stdout '0 0 0 0\n1 0 1\n' != '-5 -3 0 -2\n1 0 1\n'
FAIL  a_dialect_operation_lowers_inside_a_keyword_argument:
      stdout '0\n' != '-2\n'
```

Both are **wrong VALUES rather than crashes**, which is worth stating because the
minimal program above crashes: an emptied `args`/`kwargs` list is dropped, the
call takes the value whatever was left in the argument register, and the image
prints `0` and exits 0. The row whose construction argument is `v=<replacement>`
loses its operand; the row whose construction argument is `<replacement>` keeps
the callee's own value and reads 0. A crash needs a call whose arity or keyword
shape is checked; the rest are silent.