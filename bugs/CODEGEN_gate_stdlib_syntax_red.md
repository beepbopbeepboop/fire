# Gate job `stdlib-syntax` goes red once master is merged: `iter()` on a scalar binds a list cursor

## Status

OPEN. Root cause found; the fix is verified in a scratch copy but is NOT on this branch, because the
faulty lines were added to master by `b3814dbfd` ("iter() on an already-declared container parameter
binds a cursor"), which this branch does not contain. This branch (`work/fix-red-…-9`, HEAD `46a1d6106`)
passes every named file on its own; the red appears only in the merge with current master
(`git merge-tree --write-tree HEAD master` is clean, tree `84636db6c`).

## What was run

- Narrow syntax check of the five files the gate named, per `compile_stdlib.transpile_file`, with a
  cold `GMOJO_HOME` cache, each under `tools/memslot.py --gb 8`:
  - on this branch HEAD: `std/builtin/dtype.mojo`, `std/logger/logger.mojo`, `std/memory/address_space.mojo`,
    `std/testing/suite.mojo`, `test/collections/test_linked_list.mojo`: all PASS.
  - on the materialised merge tree (`git archive 84636db6c`): the first four PASS;
    `test/collections/test_linked_list.mojo` FAILS with 2 gcc errors:
    - `test_collections_test_linked_list_test_iter`: `it = ll` / `it = (MojoList *)…`, then
      `mojo_list_get_int(it, …)` with `it` an `int64_t` (`passing argument 1 of 'mojo_list_get_int'
      makes pointer from integer`), and `_t149 = (MojoList *)_t150` assignment from an int.

## Root cause

In `mojo/backend_gimple/emit_stmts.py::_try_bind_iter_cursor` (master):

1. `b3814dbfd` replaced the guard `name not in gen.var_types` with a rebind path: an already-declared
   target `_rebind` now proceeds when the argument's C type equals the target's.
2. The argument in `test_iter` is `ll`, from `var ll = LinkedList[Int]()`. That constructor does not
   resolve in this compiler and lowers to `ll = (int64_t)0  /* indirect call via SubscriptExpr */`, so
   `at == 'int64_t'`.
3. The `elif at in ('int', 'int64_t', 'void *')` branch (kind `'list'`, `av` coerced to `MojoList *`)
   then binds a list cursor over that scalar. `it` happens to be in `var_types` by then, so the
   rebind check (`var_types['it'] == 'int64_t' == at`) passes.

The rebind path was written for "a parameter/earlier local that holds a plain container" (its own
comment), so it must require a real `MojoList *` on both sides. Accepting an `int64_t` there is the
bug.

## The fix (verified in a scratch copy of master, not committed)

`mojo/backend_gimple/emit_stmts.py`, `_try_bind_iter_cursor`, replace

```python
    if _rebind and gen.var_types.get(name) != at:
        return False
```

with

```python
    if _rebind and (gen.var_types.get(name) != 'MojoList *' or at != 'MojoList *'):
        return False
```

Verified:
- `GMOJO_HOME=.tmp/cas-fix python3 -I .tmp/gen_c.py <master-copy> .tmp/fix.c`: the generated C for
  `test/collections/test_linked_list.mojo` is **byte-identical** (`cmp`) to the one from this branch's
  HEAD, and `gcc-mp-15 -fgimple -fsyntax-only -D__MOJO_STDLIB_MODE__` reports 0 errors (master
  unfixed: 2).
- The master commit's own test `gimple_iter_rebinds_a_parameter_to_a_cursor` (the `rest`/`twice`/`dflt`
  program, expected `(1, [20, 30]) 9 -1 9`) still PASSES with the fix (run through
  `test_gimple_stdout` directly).

## Next step

1. Land the fix on master (or on a branch made from master) in the same commit as, or immediately after,
   `b3814dbfd`'s owner: the one-line change above plus a test next to
   `gimple_iter_rebinds_a_parameter_to_a_cursor` that `iter()` on a constructor stub
   (`var ll = LinkedList[Int](); var it = iter(ll)`) does not gain a list cursor.
2. Then run the full `make gate` once, as the integrator. `stdlib-syntax` must show `U` unchanged
   (0 unexpected) and `test/collections/test_linked_list.mojo` must compile.
3. Delete this doc in that commit.

Also not yet checked: whether the `(int64_t)0` constructor stub is itself a bug (`LinkedList[Int]()` in
`test/collections/test_linked_list.mojo` should construct a real list, not 0). It is a separate gap
and the fix above does not depend on it.
