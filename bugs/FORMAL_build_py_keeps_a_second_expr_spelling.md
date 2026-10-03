# `formal/build.py` keeps a second `_expr_spelling` three lines below the alias that was meant to replace it

**Area:** `formal/build.py` · **Status:** open, not fixed here — `formal/build.py`
is claimed by several formal workers and a duplicate implementation of
`model.expr_spelling` is not a merge's business to delete.
**Found while merging** `work/formal8-9`, `work/formal8-2-r2`, `work/formal8-8-r2`
and `work/formal8-13` into `work/merge-formal8b`. It is on `master` and on all
four branches, so no merge caused it.

## What is there

    formal/build.py:2580  # The source's own spelling of an expression, and of a `.member` chain, are
                         # `model.expr_spelling` / `model.member_chain_text`.  Both used to be spelled
                         # here as well; `model.py` needs them for its own refusals and a model function
                         # must not reach up into the build pass for a string, so the model owns the one
                         # implementation and this file calls it.
    formal/build.py:2586  _expr_spelling = M.expr_spelling
    formal/build.py:2589  def _expr_spelling(node) -> str:      # …a second, older copy

The `def` shadows the alias three lines later, so the comment describes a state
the file is not in: the model owns the one implementation **and** this file keeps
its own. The same shape as
`bugs/FORMAL_nullable_pointer_aliases_is_defined_twice.md` — a dead assignment
sitting next to the live thing it was meant to be replaced by.

## Measured: the two copies disagree

The model's copy is the newer one — it spells any callee, not only a bare
`IdentExpr`, because `TypeList.reduce[Self._mapper]()` and
`Intrinsics.read[0]()` are themselves `CallExpr`s whose callee is a subscript.
That is spelled out at `formal/model.py:24576`: restricting the arm to a bare
`IdentExpr` "printed `CallExpr` — a bare placeholder, in a diagnostic whose whole
job is to name the thing — for every specialization in the new-modular stdlib".

The build pass still has the old restriction. Same input, both spellings, no
build and no memory:

    $ python3 - <<'PY'
    import fire_compiler as F, formal.model as M, formal.build as B
    tree = F.Parser(F.py_tokenize("def g(c):\n    return c.f[0]()\n")).parse_module()
    for n in M.iter_nodes(tree):
        if isinstance(n, F.CallExpr) and not isinstance(n.func, F.IdentExpr):
            print("model.expr_spelling  :", M.expr_spelling(n))
            print("build._expr_spelling :", B._expr_spelling(n))
    PY
    model.expr_spelling  : c.f[0]()
    build._expr_spelling : CallExpr

    # and `m.reduction[0](3)` → `m.reduction[0](3)` vs `CallExpr`

So every `formal/build.py` refusal that quotes a value whose callee is not a
bare name — a comptime specialization, a subscripted method — quotes the AST
node type instead of the source, in a message whose only job is to name the
thing.

## Next step

Delete the `def _expr_spelling` at 2589 (and its `__doc__`, which is the model's
docstring verbatim plus the operator arms' note) and let the alias at 2586 stand.
Then check the build pass's own messages for the change, because the alias also
covers shapes the deleted copy handled and the model does not: `SetExpr` (the
model's `expr_spelling` arms are `ListExpr`/`TupleExpr` only) and a non-`str`
`.value`/`.name` fallback. If any caller depends on those, port the arm to
`model.expr_spelling` rather than keeping a second copy.

The cheap way to see the affected diagnostics without a build is
`grep -n 'CallExpr' formal/build.py`'s message f-strings, and
`tools/formal_sweep.py`'s `codegen` bucket on the new-modular stdlib is where a
real specialization call would show up.
