# A name stored only in a `while` body is refused, though the loop provably ran

**Area:** FORMAL (`formal/model.py`'s `_build_cfg` / `_loop_body_always_runs`).
**Status: OPEN, introduced 2026-10-01 by the CFG fix for
`FORMAL_read_before_store_dominating_store.md` (that doc is deleted, fixed in
`formal3-6-r2`). Not a defect in the analysis — the store really does not
dominate on the graph the statement tree gives — but a false refusal of a
program that is correct, which is the error this path is supposed to prefer not
to make.** Pinned, not hidden:
`test_formal_read_before_store.py`'s `while_body_store_refused` carries the
`diverges` note, so a reader who finds the refusal meets its explanation in the
test that produces it.

## What I ran

```mojo
def f(n):
    var i = 0
    while i < 3:
        t = 1
        i = i + 1
    printf("t=%d", t)
    return 0
```

## What I see

CPython runs it and prints `t=1`. Both formal backends now REFUSE it, with
`model.read_before_store_refusal`:

    't' is read at line 5 before anything in this function stores it, and CPython
    raises UnboundLocalError for that program (NameError at module level) …

**Before the CFG fix this built, ran, and printed the right answer** on both
architectures — the old ordered walk added the loop body's stores to the set the
code after the loop saw, which is wrong in general and right here.

## Why the CFG cannot see it

Whether the body runs at least once is a question about the CONDITION ON ENTRY,
and the graph `_build_cfg` builds says nothing about values: the loop's
preheader is a predecessor of the join, and that edge is the "zero iterations"
path, so the join intersects it with the latch and the body's definitions drop
out. `_loop_body_always_runs` is the one place that can remove that edge, and it
answers only where the answer is decidable from literals
(`formal/model.py`'s docstring is the argument):

* `while True:` / `while 1 < 2:` — a literal-true condition, so the body runs.
* `for i in range(3)`, `for i in [1, 2, 3]`, `for i in "abc"` — a non-empty
  literal iterable.

`while i < 3` with `i` a local is none of those.

## The next step, and it is one fact

**Decide the condition on entry for a name whose every binding in the function
is a literal.** `i = 0` in the preheader and `while i < 3` is decidable, and
`i = f()` is not — so the rule is: if the condition is a comparison of a NAME
against an integer literal, and every binding of that name reachable before the
loop is an integer literal, evaluate it; otherwise keep the zero-iteration edge.

This is the same shape as `_loop_body_always_runs` and belongs in the same place,
so it composes with it rather than becoming a second rule with its own reading
of "did it run": one predicate, two sources of evidence (the condition's own
literals, and the preheader's constants). The existing fixpoint already carries
the preheader's IN set per block, so the bindings are reachable without a second
walk — `model.returns_on_every_path` shows the module's habit of keeping the
strict reader in `model` rather than in a backend for exactly this reason.

**Measure before building it**: the honest number is how much of the corpus
stops on this. `while i < 3: t = …` is rarer than `while True:`, which is why
the literal rule landed first, but a sweep of the two shapes is what says whether
the constant propagation is worth the second source of evidence.

## Not measured here

- the sweep delta for this refusal (a sweep is the integrator's, not a worker's);
- whether a NAME's bindings can always be recovered from the block IN sets, or
  whether the `_name_bindings` walk `_offset_scale` uses is the right reader —
  that is the question the first implementation has to answer, and it is a real
  one rather than a formality.
