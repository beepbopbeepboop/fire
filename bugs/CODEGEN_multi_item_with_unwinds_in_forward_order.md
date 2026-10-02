# CODEGEN: a multi-item `with` unwinds its context managers in the WRONG order

**State: OPEN, unfixed.** Found while fixing
`CODEGEN_with_no_as_target_drops_exit.md` (now deleted). Independent of it:
that one was `with C():` dropping the teardown, this is `with A() as a, B():`
running BOTH teardowns in the wrong order. It is not caused by that fix and the
`as` spelling was always affected.

## What I ran and what I saw

    class Ctx:
        def __init__(self, n):
            self.n = n
        def __enter__(self):
            print("enter", self.n)
            return self.n
        def __exit__(self, a, b, c):
            print("exit", self.n)

    def f():
        with Ctx(6) as a, Ctx(7):
            print("multi", a)
    f()

| | |
|---|---|
| CPython | `enter 6` / `enter 7` / `multi 6` / `exit 7` / `exit 6` |
| compiled | `enter 6` / `enter 7` / `multi 6` / `exit 6` / `exit 7` |

Real Python unwinds in reverse acquisition order, which is the whole point of
nesting: an inner context manager may depend on an outer one's state still
being live. The compiled path releases the outer one first.

`@contextlib.contextmanager` items are affected identically — the generator arm
registers through the same index-parallel lists.

## Mechanism

`_with_emit_exits` (`mojo/backend_gimple/emit_stmts.py`) walks the lists
forward:

    for _xi in range(len(_ex_ts)):

and its own docstring says "in reverse-independent index order", which reads as
a deliberate choice rather than an oversight — so whoever picks this up should
establish WHY before changing it, since reversing the walk also reorders the
generator arm's final `resume()`/`destroy()` pair relative to the neighbouring
`__exit__`.

## Next step

Iterate `range(len(_ex_ts) - 1, -1, -1)`. The shape-independent check is a
two-item `with` where the two `__exit__`s print, compared against CPython —
which is what `test_gimple_runner.py`'s new
`test_gimple_matches_cpython` helper makes a two-line test.

Not fixed here rather than fixed here: it is a semantic change to the unwind
order of every multi-item `with` in the tree, it is orthogonal to the no-`as`
teardown drop this branch was working, and the fix that WAS needed there is a
`make gate` change on its own.

## Also measured on the same tree, and deliberately left alone

Both pre-existing, both `as`-independent, both deliberate divergences from
CPython rather than defects:

* **A class with `__exit__` but no `__enter__`** is treated as a no-op context
  manager by the compiled path (the `else` arm at the `__enter__` probe emits
  a placeholder and falls through), where CPython raises
  `TypeError: 'X' object does not support the context manager protocol
  (missed __enter__ method)`. Same in the other direction for `__enter__`
  without `__exit__`.
* **`__exit__(self)` with one parameter** is padded to its declared arity,
  where CPython rejects it (the protocol requires the 3 exception-info
  parameters). The padding is documented and intentional in `_with_emit_exits`
  ("Real Mojo (unlike Python) does NOT require `__exit__` to accept the 3
  exception-info params"), so the compiled path is right for Mojo and
  diverges from CPython on purpose.