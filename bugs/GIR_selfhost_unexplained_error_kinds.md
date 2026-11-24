# GIR selfhost: the error kinds nobody has diagnosed yet

Part of the whole-closure self-host failure (`python3 test_selfhost.py`). See `doc/GIR.md`,
section "Selfhost closure: remaining errors". The extern-return-type family is in
`bugs/GIR_selfhost_extern_return_types.md`; this doc is everything else.

## Counts (baseline at `8f244354d`, `kinds_selfhost_before.txt`; gcc `error:` lines)

These are the families that were NOT touched by the fixes merged on 2026-11-24. Each is a
separate gcc message kind, so each is a separate root cause until shown otherwise.

| count | gcc message |
|---|---|
| 11 | `'Scope' has no member named 'declared_types'` |
| 10 | `'MojoFunction' has no member named 'param_types'` |
| 10 | `non-trivial conversion in 'component_ref'` |
| 8 | `'Interpreter' has no member named '_try_depth'` |
| 5 | `'Interpreter' has no member named '_sys_proxy'` |
| 5 | `'MojoFunction' has no member named '_interp'` |
| 4 | `'MojoFunction' has no member named 'return_type'` |
| 3 | `'Scope' has no member named 'nonlocals'` |
| 3 | `invalid operands to binary + (have 'MojoList *' and 'double')` |
| 3 | `assignment to 'int64_t' from 'struct Scope *' makes integer from pointer` |
| 2 | `'Interpreter' has no member named 'global_vars'` |
| 2 | `'MojoOverloadSet' has no member named '_interp'` |
| 1 | `'MojoClass' has no member named 'keywords'` |
| 1 | `'MojoFunction' has no member named 'comptime_param_defaults'` |
| 1 | `'ReturnValue' has no member named 'node'` |
| 1 | `non-trivial conversion in 'var_decl'` |

What was fixed on master, and so is NOT in this table any more (verify with the master run):
`'_FLOAT'/'_SIGNED'/'_UNSIGNED' undeclared` (funcptr branch, `fa8f13afa`), `invalid operands
to binary` on doubles (float8, `65454bf70`), `expected expression before '('` (coro,
`92e4e806a`), `makes integer from pointer` for `MojoDict *` in `emit_funcs.py` (funcptr,
`77abd738a`).

## Why these look like one problem, and why they might not be

Almost all of the `has no member` kinds name attributes of compiler-internal classes
(`Scope`, `MojoFunction`, `Interpreter`, `MojoOverloadSet`, `ReturnValue`). In the generated C,
those are struct fields emitted from the Python class's attribute set. A missing field means the
struct layout the importer sees is not the one the defining module emitted: the same
layout-drift family as `bugs/` "self-host struct layout", and `doc/GIR.md` stage 5c's
mixed-field work. Check that first. It is a hypothesis, not a finding.

`non-trivial conversion in 'component_ref'` (10) and `'var_decl'` (1) are gcc GIMPLE checks: a
component or variable is assigned a value whose C type differs from the field or declaration.
They are probably the same class of type mismatch as the extern-return-type family.

A separate anomaly: a selfhost run from inside the agent worktree gave 201 gcc errors, mostly
`myinterpreter.py` redefinitions and missing members, against 67 from the scratch copies of the
same tree. Its cause was not found. Any future selfhost comparison must run from a clean
scratch copy (see `test_selfhost.py` and the copy method in the 2026-11-24 log), not from a
checkout that has other untracked files in it.

## Next step

1. Re-run `python3 test_selfhost.py` on master (after `913aa3780`) and regenerate the table,
   since the WIP changes some rows.
2. Take the largest unexplained row first (`'Scope' has no member named 'declared_types'`,
   11): find the struct it reads (`grep -n "declared_types" mojo/`), compare the `.ci` field
   list for that struct in the closure dump with the Python class, and find which side is stale.
3. Then `'MojoFunction'` (10 + 5 + 4 + 1) the same way.
4. Each row gets its own status entry here with the exact count before and after.

## Status

- 2026-11-24: counted from the baseline. Not diagnosed. Nothing in this family has been changed.
