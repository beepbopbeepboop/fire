# FORMAL_nested_comprehension_generator_temps_are_not_collected: a comprehension inside a comprehension's iterable has no home

**Area:** FORMAL (both backends — the temp-name collector is
`formal/arm64_codegen.py::_collect_var_names`, and x86-64 has the same
function).
**Status: OPEN, measured, and NOT caused by anything in the comprehension-scope
work on `work/formal13-6` — re-measured with that patch reverted, so it is not a
regression from it.**

Found 2026-10-03 while adding `bugs/FORMAL_string_value_model.md`'s comprehension
scope, on `work/formal13-6`.

## What was run

```console
$ cat .tmp/probe2/b.mojo
def main(n: Int) -> Int:
    var r = [y for y in [x for x in ["a", "", "c"] if x]]
    return len(r)

$ for a in arm64 x86_64; do python3 tools/memslot.py --gb 8 --label p -- \
      python3 fire.py build --formal --no-prove --backend=$a -o .tmp/b.$a .tmp/probe2/b.mojo; done
build: main: '_cb1' has no home: the register allocator collected no home for
it, so the emitter and the allocation walk disagree about this function's locals.
…
```

Both architectures, byte-identical wording. The SAME source builds and answers 1
with the inner comprehension alone (`[x for x in ["a", "", "c"] if x]`), so the
nest is the whole of it.

## What is expected

`len(r)` is 1. CPython agrees, and so does this backend on the unnested spelling.

## What it is

The comprehension walk allocates `_ci{d}`/`_cb{d}` — one index and one
iterable-pointer temp per generator — from a nesting counter `d`, and the
collector that reserves their names (`_collect_var_names`'s `walk_compr`)
disagrees with the emitter about `d` for a comprehension that appears in a
generator's ITERABLE:

```python
def walk_compr(node, depth, acc):
    if isinstance(node, F.Comprehension):
        n = len(node.generators or [])
        acc[0] = max(acc[0], depth + n - 1)
        for g in node.generators or []:
            walk_compr(g.iterable, depth, acc)          # <-- `depth`, not `depth + n`
            …
```

`_emit_comprehension` sets `self._compr_depth = d0 + len(gens)` for the WHOLE
walk, not per generator, so a nested comprehension reached from generator `gi`'s
iterable is emitted at depth `d0 + n`. The collector reserves `d0 + n - 1`. The
inner comprehension therefore asks for `_ci1`/`_cb1` and the collector only ever
reserved `_ci0`/`_cb0`, so the emitter has no home for it.

**The two conventions differ by exactly one, and which is wrong is a decision
rather than a fix.** `depth + n` in the collector matches the emitter today and
is the one-line change; `d0 + gi` in the emitter is the tighter allocation and
matches Python's own scoping (generator `gi`'s iterable sees generators
`0 … gi-1` open), but it moves the counter for every comprehension, so the
45-file per-stage sweep in `bootstrap` is the measurement that decides which.

Measured consequence of the current state: **every nested comprehension is
refused**, on both machines, with a message that names an internal table
("the register allocator collected no home for it") rather than the construct.
The nested comprehension is ordinary Python and ordinary in the stdlib
(`sum([y for y in [x for x in row] if x])`-shaped code is everywhere), so this
is a coverage row, not an exotic one.

## The next step

1. Change `walk_compr`'s `g.iterable` argument from `depth` to `depth + n`, so
   the collector and the emitter agree, and add a `test_formal_run.py` case in
   `BOTH_ARCH_CASES` (the nesting is what puts the two conventions out of step,
   so it must be checked on both machines — see the row added by
   `work/formal13-6`, `both_arch_loop_and_comprehension_variable_hold_an_element`,
   for the shape).
2. Measure the stdlib row with `tools/formal_sweep.py` (an integrator's job), and
   expect the ceiling to be low: the refusal is loud, so the files that move are
   the ones whose next construct is also answerable.
3. The tighter emitter-side counter (`d0 + gi`) is worth doing afterwards, and
   only with the sweep delta in hand — it changes where every comprehension's
   temps sit, which is a codegen-level change to `formal/arm64_codegen.py` and
   `formal/x86_64_codegen.py` and therefore owes a full `make gate`.

Note that a comprehension in a generator's CONDITIONS or in the ELEMENT is
already walked at `depth + n` by the collector and does not hit this — only the
iterable does, which is why the reproducer puts the nesting there.

## Reproducing

```
$ python3 tools/memslot.py --gb 8 --label p -- \
      python3 fire.py build --formal --no-prove --backend=arm64 .tmp/probe2/b.mojo
build: main: '_cb1' has no home: …
```
