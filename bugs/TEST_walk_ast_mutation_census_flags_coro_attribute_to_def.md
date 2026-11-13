# TEST: `test_gimple.py`'s AST-mutation census fails on master: `mojo/middle/coro.py::_attribute_to_def` writes `line`/`col` without invalidating the walk memo

Status: OPEN. Found 2026-11-12 while merging master into a worker branch; the
two files involved (`mojo/middle/coro.py` and `test_gimple.py`) are byte-
identical to master at `4f0c96712`, so this is master's own red, not a merge
artefact. Not fixed here: the file belongs to another lane's generator work.

## Symptom

`python3 test_gimple.py` (the registered `gimple` job, in `check`) ends

```
FAIL  every_ast_mutation_site_invalidates_the_walk_memo: 1 problem(s):
  mojo/middle/coro.py::_attribute_to_def writes an AST node's field
  (4635 `line`, 4636 `col`) and never invalidates the memo - either call
  `_walk_ast_invalidate(<the node it wrote>)` there, or add the key to
  `_WALK_AST_MUTATION_ALLOWLIST` with the reason
...
Results: 448 passed, 1 failed
```

`_attribute_to_def` was added by `681c07503` ("codegen: stack-switch
generator bodies carry #line directives"):

```python
def _attribute_to_def(prologue: list, fn) -> list:
    ...
    for stmt in prologue:
        stmt.line = fn.line
        stmt.col = fn.col
    return prologue
```

The census test flags any write to a dataclass field from `fire_compiler.py`
that is not accompanied by `_walk_ast_invalidate(...)`/`_walk_ast_reset(...)`
or an entry in `_WALK_AST_MUTATION_ALLOWLIST` (`test_gimple.py:68`).

## Reproduction

```
python3 tools/memslot.py --gb 8 --label walkmemo -- python3 test_gimple.py
```

`448 passed, 1 failed`, the single failure being the case above. It is stable
across runs and does not depend on test order (`_run_isolated`).

## Expected / next step

Both call sites of `_attribute_to_def` (`_async_method_setup` around
`mojo/middle/coro.py:4668`, and the async-generator lowering around
`mojo/middle/coro.py:8556`) run in `lower()`, before `gen_module` walks the
tree, and the prologue `VarDecl` nodes it writes are freshly synthesized, so
the production-quality fix is very likely the allowlist form the census
already uses for its neighbours:

```python
"mojo/middle/coro.py::_attribute_to_def": "`lower()` only, and the prologue it
    attributes is freshly synthesized, so no walk has seen those nodes",
```

If a path through `gen_module` can instead reach a prologue the memo has
already walked, call `_walk_ast_invalidate(stmt)` in the loop (and then the
allowlist entry is not needed). Confirm which by checking the two call sites
before choosing; the census's message names exactly these two options.

## Done when

`python3 test_gimple.py` is green again (the `gimple` job), with either the
invalidation call or a reasoned allowlist entry.
