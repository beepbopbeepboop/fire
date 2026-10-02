# TEST: `imports: every real entry point imports first` is red — `mojo.backend_gimple.module_gen` closes a cycle nothing declares

**Found 2026-10-02 by `bugs4-9`** while closing
`bugs/TEST_estate_check_red_on_two_form3_test_files.md` (deleted with its fix):
`test_suite.py` has a second failure, on the same run, that is pre-existing on
`bc17a62b` and belongs to nobody. Measured on a pristine
`git archive bc17a62b` extraction, so it is not a change in flight.

## What was run

```
$ python3 test_suite.py
...
Results: 297 passed, 1 failed
  - imports: every real entry point imports first: mojo.middle.calls_shared:
    ImportError: cannot import name 'user_dunder_repr_call' from partially
    initialized module 'mojo.middle.calls_shared' (most likely due to a
    circular import); … (nine modules, listed below)
```

`suite-self-test` is registered in `check`, `gate` and `smoke`, so this is a red
in the everyday loop.

## The exact cycle

```sh
$ python3 -c "import mojo.backend_gimple.module_gen" 2>&1 | grep '^  File'
  File "mojo/backend_gimple/module_gen.py", line 42, in <module>
  File "mojo/middle/infra_infer.py", line 21, in <module>
  File "gimple_codegen.py", line 738, in <module>
  File "mojo/backend_gimple/emit_methods.py", line 34, in <module>
  File "mojo/backend_gimple/emit_funcs.py", line 42, in <module>
  File "mojo/backend_gimple/emit_calls.py", line 40, in <module>
  File "mojo/backend_gimple/emit_exprs.py", line 42, in <module>
  File "mojo/backend_gimple/emit_infra.py", line 60, in <module>
ImportError: cannot import name '_FC_SEP' from partially initialized module
'mojo.middle.infra_infer'
```

`module_gen` is a `mojo/backend_gimple/*` module, and the check's own comment is
explicit that none of those is exempt:

> No `mojo/backend_gimple/*` module is exempt: the backend sits downstream of
> `gimple_codegen`, so every one of them is reachable first and a new cycle
> among them would be caught here.

So this is the check working: a new cycle among the backend modules appeared and
the check caught it. What it does NOT do is tell you whether the cycle is
harmless.

## Why it is harmless today, and what that does not prove

`gimple_codegen.py:738` is module-level code in a module that
`mojo/middle/infra_infer.py` imports — so the middle tier is upstream of the
gimple tier in this graph, exactly as the check's comment assumes for the eight
declared `mojo/middle/*` exemptions. But `module_gen` is DOWNSTREAM of
`gimple_codegen` and imports `mojo.middle.infra_infer` at line 42, so entering
through `module_gen` runs `infra_infer` first, which runs `gimple_codegen`,
which runs the whole backend, which comes back to `infra_infer` — and
`infra_infer` is only half-initialised.

Every real entry point still works, because every real one is `fire`,
`fire_main`, `myinterpreter`, `reflect`, `gimple_codegen`, `formal.build`,
`formal.model` or a `mojo/backend_gimple/*` module reached from one of those.
So: **nine modules cannot be a process's FIRST `mojo.*` import, and every
program works.** That is the same state the eight declared exemptions are in,
one tier downstream.

## The next step, exactly

Two consistent outcomes, and the choice belongs to whoever owns the backend's
import graph:

1. **Declare it.** Add `'mojo.backend_gimple.module_gen'` to `declared` in
   `test_suite.py`'s `test_import_entry_points`, with a comment saying
   `module_gen` is downstream of `gimple_codegen` in the same way the eight
   middle-tier modules are upstream of it — `gimple_codegen.py:738` importing
   `emit_methods` at module level is the edge that closes the loop. This is the
   smaller edit and it keeps the check's other half working: the
   `declared <= failed` direction means a later fix that breaks the cycle has to
   DELETE the entry in the same commit, which is the anti-rot the whole
   declaration exists for.
2. **Break the cycle**, which is the real fix and is not a one-liner:
   `gimple_codegen.py:738`'s module-level `from mojo.backend_gimple
   .emit_methods import ...` (and whatever else it pulls at import time) would
   have to move behind a lazy import or a function-level call. That is a change
   to the top of the most-imported module in the tree and it deserves its own
   pass with the full gate, not a drive-by from a bug-fix branch.

Do NOT widen the check to "exempt anything that fails" — the `declared <= failed`
half is what stops that list becoming a place where cycles go to die.

## Coverage

`test_suite.py`'s own `test_import_entry_points` is the check; the second
assertion in it (`the load-order exemption list is not stale`) is the one that
makes whichever outcome above correct — it fails if an exemption stops being
needed.