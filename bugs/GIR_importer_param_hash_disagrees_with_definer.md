# GIR: an importer compiled before its definer hashes the definer's parameters as `int64_t`

Found 2026-11-25 by the `mojoc` and `selfhost` gate jobs once the gcc errors were gone (the closure
TU now compiles with 0 gcc errors; the LINK fails). Part of `make gate` red; see
`bugs/GATE_selfhost_and_mojoc_link_failures.md`.

## Symptom

`ld: Undefined symbols` for five functions of the middle tier, each referenced under one overload
suffix and defined under another (closure TU `tools/selfhost_ci.py`, `selfhost.ci` at `e0d1e6aa0`):

| function | referenced as (importer) | defined as (definer) |
|---|---|---|
| `funcs_shared.annotated_return_ctype` | `_ba2192 (GimpleGen *, int64_t fn_node)` | `_4b4aec (GimpleGen *, FunctionType *)` |
| `funcs_shared._selfhost_gen_self_param_ctype` | `_789b7e (GimpleGen *, int64_t, int64_t, int64_t)` | `_9adbdc (GimpleGen *, char * pname, int64_t, int64_t)` |
| `calls_shared._null_default_pair` | `_c2eb2a` | `_1b532c (char *, char *)` |
| `calls_shared._pack_kwargs_dict` | `_ba2192` | `_d08fb7 (GimpleGen *, MojoDict *)` |
| `calls_shared.user_dunder_repr_call` | `_6b5e66` | `_d43d4b (GimpleGen *, char *, char *, char *, MojoList *)` |

Some callers use the definer's suffix (the ones compiled after it) and some the all-`int64_t` one
(the ones compiled before), so the closure holds both spellings and only one is defined; the other
is a weak `_MOJO_STUB_` prototype or nothing.

## Cause (measured, not yet fixed)

The suffix hashes the parameter C types (`overload_suffix_for`). The definer refines its parameters
from call-site evidence (`_gmi_apply_call_site_param_evidence`: `fn_node` becomes `FunctionType *`);
an importer inline-compiled earlier, inside the 76-module import cycle, takes the fallback
`_home_signature_ctypes(definer, fs)` (`funcs_shared._definer_committed_pts` has no committed answer
yet), which has no call-site evidence, so `int64_t`. The same cycle that made RETURN types
order-dependent (fixed by the solver's early decision) makes PARAMETER types order-dependent.
This is exactly stage S4 of `bugs/GIR_type_solver.md` ("parameters and the overload hash").

## Next step (pick one; both are real work)

1. (S4) Take the importer's parameter types from the solver (`mojo/tsolve`'s `Solution`, as
   `emit_funcs._early_return_decision` does for returns) and make the definer obey the same frozen
   list, so both hash the same thing. Needs a `Solution.param_stys(path, name)`, a `lower` for each,
   and the definer's call-site refinement must not override a frozen entry.
2. (cheaper, measured first) Do not hash these five: they are called only from inside the
   compiler, so `_NO_OVERLOAD_MANGLE` (no suffix) removes the mismatch by construction. That is a
   workaround for these names only; the class stays open for the next function.

## Test

The closure link: `python3 tools/suite.py selfhost mojoc` must get past `ld`. A reduction is not
yet written: it needs a cycle of two modules where the importer is compiled first and the callee's
parameter is refined by its call sites (build with `fire.py build`, link mode).
