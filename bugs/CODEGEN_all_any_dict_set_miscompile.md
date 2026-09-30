# CODEGEN_all_any_dict_set_miscompile: `all(d)`/`any(s)` reinterpret dict/set as list

## Status (2026-09-13 — FULLY FIXED same day, both statically-known and boxed cases)

The residual boxed/untyped-handle gap (below) is now closed too: the
consolidated `gimple_gen_infra._materialize_as_list` (DESIGN.html R1 follow-
up, shared by `all()`/`any()`/`enumerate()`/`str.join()`/`bytes.join()`/
`shlex.join()`) now guards a genuinely-unknown handle with
`mojo_is_registered_dict`/`mojo_is_registered_set` at runtime instead of
blindly assuming list — DESIGN.html R5, done for this one function (all 5
call sites inherit it at once). No behavioral gap remains for any of the 5
call sites this doc covers.

## Status (2026-09-13 — PARTIALLY FIXED same day, statically-known case only)

Fixed the case where `at` (the argument's static C type) is exactly
`MojoDict *` or `MojoSet *`: `_lower_builtin_all_any` in
`gimple_gen_calls.py` now materializes via `mojo_dict_keys`/
`mojo_set_sorted` before calling `mojo_list_all`/`_any`, instead of
reinterpreting the dict/set header as a list.

**Still open**: when the argument reaches this function as a genuinely
untyped/boxed pointer (`void *` or another opaque pointer whose real kind
isn't statically known), the code still blindly casts to `MojoList *`.
Fixing that residual case needs a runtime `mojo_is_registered_dict`/
`_set` guard (DESIGN.html R5), which duplicates the call-emission per
branch — not attempted in this pass. See the original write-up below for
the full original analysis (still accurate for the boxed/unknown case).

## Status (2026-09-13 — found during DESIGN.html R3 cast-migration audit, NOT fixed)

Found while migrating ad-hoc container-kind casts to the `_coerce_to_type`
chokepoint (DESIGN.html R3). `_lower_builtin_all_any` in
`gimple_gen_calls.py` (~line 2129):

```python
def _lower_builtin_all_any(gen, fname_raw, node):
    runtime_fn = 'mojo_list_all' if fname_raw == 'all' else 'mojo_list_any'
    ...
    at, av = gen.lower_expr(node.args[0])
    t = gen._new_temp('int')
    if at == 'MojoList *' or (at.endswith(' *') and at != 'char *'):
        lv = av if at == 'MojoList *' else gen._new_val('MojoList *', f'(MojoList *){av}')
        gen._emit_call('int', t, runtime_fn, [('MojoList *', lv)])
```

The guard `at.endswith(' *') and at != 'char *'` accepts ANY pointer type
except `char *` — including `MojoDict *` and `MojoSet *` — then
reinterprets it as `MojoList *` via a hard cast with no runtime kind check.
`all(some_dict)` / `any(some_set)` (both real, common Python: iterating a
dict yields its keys, a set yields its elements) index the dict/set's
memory as if it were a list header — the exact SIGBUS-class miscompile
DESIGN.html's R2/R4 sections describe, just not yet hit by an actual repro.

No `mojo_dict_all`/`mojo_set_all` (or `_any`) runtime entrypoints exist
(confirmed via `grep -rn "mojo_dict_all\|mojo_set_all\|mojo_dict_any\|
mojo_set_any" runtime/ gimple_*.py` — no hits), so there is no cheap
existing runtime function to route to directly.

**Not fixed in this pass**: routing this cast through the R2 chokepoint
(`gen._coerce_to_type(at, 'MojoList *', av)`) would immediately `raise` at
compile time for any `all(dict)`/`any(set)` call, turning a silent
miscompile into a hard build failure — arguably the *correct* R2 behavior,
but a real behavior/coverage change that needs verifying no in-tree stdlib
source actually relies on the current (wrong) silent path before flipping
it, which is out of scope for a mechanical cast-migration pass.

## Suggested fix

Two options, in order of preference:
1. Add `mojo_dict_all`/`mojo_dict_any`/`mojo_set_all`/`mojo_set_any` to the
   runtime (iterate keys/elements, short-circuit), and dispatch on `at` in
   `_lower_builtin_all_any` instead of blanket-casting to `MojoList *`.
2. Materialize keys/elements first (`mojo_dict_keys`/no direct
   set-to-list helper exists yet either — would need one, see
   `mojo_set_sorted` as the closest existing set→list conversion) and run
   `mojo_list_all`/`mojo_list_any` on that, at the cost of an extra
   allocation.

Either way, run `compile_stdlib.py` before/after to confirm no in-tree
`all(dict)`/`any(set)` call site currently depends on (mis)compiling
through the list path.
