# `_compute_exc_descendants`'s call-site result temp is the box while its definition is `MojoDict *`

## Status: OPEN. Found 2026-10-03 while working
## `bugs/hard/CODEGEN_dispatch_globals_list_forces_every_name_to_a_dict.md`.
## One of 11 residual `selfhost` errors, and the last one of the four defects
## that doc's own fix uncovered.

## What I ran

    python3 tools/suite.py selfhost
    # FAIL  selfhost  (110s)  exit 1

and the generated-C error inventory described in that doc's "How it is measured
now" section:

    fire_nl.ci:941360:10: error: assignment to 'int64_t' {aka 'long long int'}
        from 'MojoDict *' makes integer from pointer without a cast [-Wint-conversion]

## What I saw

    _t4985 = _compute_exc_descendants (all_struct_defs);   // _t4985 : int64_t
    _t4986 = (int64_t)_t4985;
    _t4984 = (MojoDict *)_t4986;                           // _t4984 : MojoDict *

inside `mojo_backend_gimple_module_gen_gen_module_impl_7e9a9f`, i.e.
`mojo/backend_gimple/module_gen.py:3257`:

    self._exc_descendants = _compute_exc_descendants(all_struct_defs)

Three different answers for one call, and the first is the odd one out:

* the DEFINITION, emitted at `fire_nl.ci:91076`, is
  `MojoDict * _compute_exc_descendants (MojoList *)`;
* `_t4984`, the assignment's destination coercion, is `MojoDict *`;
* `_t4985`, the CALL's own result temp, is `int64_t`.

## Why

`_t4985`'s type comes from `gen.func_return_types['_compute_exc_descendants']`
at the call site, and that table is first-writer-wins across the whole closure.
Two writers, in this order:

* `module_gen.py:8649-8651` seeds it from
  `gimple_codegen._selfhost_syms()` — i.e. from `_SELFHOST_SIGS` — with
  `if _shn not in self.func_return_types`, so only if nothing got there first.
  This entry used to be the stale `int64_t` (fixed in
  `bugs/hard/CODEGEN_dispatch_globals_list_forces_every_name_to_a_dict.md`'s
  commit; it is `MojoDict *` now, matching
  `mojo/middle/types.py:1862`'s `def _compute_exc_descendants(...)`, whose body
  builds and returns `descendants = {name: {name} for name in by_name}`).
* `module_gen.py:5031` then assigns UNCONDITIONALLY:
  `self.func_return_types[_as_s_p1.name] = inferred`, from
  `_infer_return_type(body)`.

So after that fix the remaining `int64_t` is a third source. The emitted
definition is `MojoDict *`, so the BODY emitter's inference and
`func_return_types` disagree for this one function — which is the same shape as
the `Parser__parse_expr` story `gimple_codegen.py:489-515` and
`mojo/middle/infra_infer.py:1659` already document for a different function, and
which is why those three tables exist at all.

Note the destination coercion (`_t4984`) is right and the call temp is wrong, so
the read is not silently miscompiled — it is a hard error, which is the better
half.

## Exact next step

Instrument one self-host build to print, for this one name, what each writer put
into `func_return_types` and in what order:

* `module_gen.py:5031` (`inferred = self._infer_return_type(_as_s_p1.body)`,
  then the assignment),
* `module_gen.py:8651` (the `_selfhost_syms` seed),
* the emitted-definition path that produced `MojoDict *` at `fire_nl.ci:91076`.

Whichever of the two produces `int64_t` for a dict-returning body is the bug; if
it is 5031's `_infer_return_type`, the fix belongs beside
`mojo/middle/infra_infer.py`'s conflicting-binding rule (a local rebound to more
than one pointer kind records the box), because `_compute_exc_descendants`
rebinds `descendants`-adjacent names across its `stack`/`seen` loop.

Whichever it is, the durable answer is ONE authority for a self-host function's
return type rather than three tables that can disagree — `gimple_codegen.py`'s
own `_SELFHOST_SIGS` comment already says the four consumers "still CAN drift
from the codegen's own inferred definition types ... which is inherent to
declaring a sibling module's symbol before that module has been inlined".