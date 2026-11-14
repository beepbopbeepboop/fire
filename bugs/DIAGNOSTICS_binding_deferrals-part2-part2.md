# DIAGNOSTICS binding deferrals part 2 — part 2: report lacking evidence at declaration time

Part 2 of 2 of `bugs/hard/DIAGNOSTICS_binding_deferrals-part2.md` (itself part 2
of `bugs/hard/DIAGNOSTICS_binding_deferrals.md`). Part 1 is
`DIAGNOSTICS_binding_deferrals-part2-part1.md`: it adds
`elaborate.type_arg_bound_evidence`. This part calls it from the
declaration-time signature check and reports the diagnostic.

## Class
mid. One wiring change in `mojo/backend_gimple/module_gen.py` plus the
end-to-end test that already exists in the tree.

## Current state (measured 2026-11-13)

Modular's `failed_binding_deferrals.mojo` second case is a PARAMETER type:

```mojo
def successful_binding[U: Movable & Deinitable](
    x: NeedsCopyablePos[CondCopyable[U], 1]
):
    pass
# CHECK: error: invalid bindings in signature: lacking evidence
```

`NeedsCopyablePos[T: Copyable, n: Int]` requires `T: Copyable`; `CondCopyable`
carries `Copyable` only `where conforms_to(T, Copyable)`, and this signature's
`U` is bounded only by `Movable & Deinitable`. So the requirement is neither
provable nor provably false.

The declaration-time hook landed for part 1 lives at
`mojo/backend_gimple/module_gen.py::_check_fn_signature_binding_violations`
(called from `gen_module_impl`). It walks every `FunctionDef` (including
struct methods and `gen._stripped_generic_fns`), parses a parameter's generic
instantiation, binds its type arguments with `elaborate.bind_type_args`, and
calls `elaborate.check_where_clauses`; a `WhereConformanceError` becomes
`error: violated constraint`. It never looks at the struct's type-parameter
bounds, so the signature above compiles silently.

Measured on this tree, the test that pins it fails:

```
python3 tools/memslot.py --gb 8 --label binding-deferral-p2 -- python3 -c "import test_binding_deferral_diagnostic as t; t.test_signature_unproven_binding_reports_lacking_evidence()"
```

ends with `AssertionError: an unproven binding in a signature compiled`
(peak 0.6 GB).

## Goal

A function DECLARATION whose parameter type is a generic struct instantiation
with a type-argument bound that is neither provable nor provably false fails to
compile with modular's wording,
`error: invalid bindings in signature: lacking evidence`, exactly once.

## Plan

1. In `_check_fn_signature_binding_violations`, after `bind_type_args` has
   produced `targs` and only when `check_where_clauses` returned without
   raising, compute the enclosing function's bound facts with
   `elaborate._fn_known_bounds(fn, module_src, None)` — it returns
   `{'U': {'Movable', 'Deinitable'}}` for the signature above (the third
   argument is unused).
2. For each `(param, bound)` in `elaborate.parse_bounds(tmpl)` with a non-empty
   `bound`, call
   `elaborate.type_arg_bound_evidence(struct_module_src or module_src, tmpl,
   param, str(targs.get(param)), fn_bounds)`.
   If it returns `'unproven'`, raise `RuntimeError` whose message carries the
   existing location prefix (`{file}:{line}:{col}: ` from the same
   `_cfn`/`_cln`/`_clc` code the `violated constraint` branch uses) followed by
   `error: invalid bindings in signature: lacking evidence`. A `note:` line
   naming the requirement/type argument is optional (it must not contain
   `error:`).
3. Keep the existing `except RuntimeError: raise` so the diagnostic escapes the
   broad exception swallow. Do not report anything when
   `_find_struct_template_source` returns no template, and do not run the
   evidence check when the `where` clause already raised: the two diagnostics
   are mutually exclusive for one binding.
4. The loop raises on the first unproven parameter, so one declaration reports
   exactly one `error:` line. Value parameters (`n: Int`) resolve to
   `'unknown'` and are accepted, so only real trait bounds report.
5. Do not touch `emit_resolve.py` / `elab_intu.py`: body instantiations keep
   their present behaviour (`test_satisfied_generic_binding_compiles` pins
   `var a = NeedsCopyablePos[CondCopyable[U], 1]()` as compiling). Whether the
   same evidence rule should reach body instantiations stays a follow-up
   decision in the parent doc's Status, not a change here.
6. In `test_binding_deferral_diagnostic.py`, extend
   `test_signature_unproven_binding_reports_lacking_evidence` with the second
   positive control from the parent doc's Acceptance:
   `def g[U: Movable & Deinitable & Copyable](x: NeedsCopyablePos[CondCopyable[U], 1])`
   compiles. Then add the function to the file's `__main__` list.

Dependency: if `elaborate.type_arg_bound_evidence` is not on your branch, part 1
has not landed. Stop and report that (NEEDS-INFO/BLOCKED); do not re-implement
the decision here.

## Acceptance

- `def successful_binding[U: Movable & Deinitable](x: NeedsCopyablePos[CondCopyable[U], 1])`
  fails to compile with exactly one `error:` line containing
  `error: invalid bindings in signature: lacking evidence`, and no
  `violated constraint` text.
- Positive controls compile: `x: NeedsCopyablePos[Int, 1]` and
  `def g[U: Movable & Deinitable & Copyable](x: NeedsCopyablePos[CondCopyable[U], 1])`.
- `test_signature_failed_binding_reports_violated_constraint` still passes
  unchanged: the `n == 0` binding reports only `error: violated constraint`,
  with no `lacking evidence` noise.
- The body-instantiation regressions in the same file still pass, in particular
  `test_satisfied_generic_binding_compiles`.

## Done when

File: `test_binding_deferral_diagnostic.py` (the test function is already in
the tree; this part makes it pass and extends its positives).

Command:

```
python3 tools/memslot.py --gb 8 --label binding-deferral-p2 -- python3 -c "import test_binding_deferral_diagnostic as t; t.test_signature_unproven_binding_reports_lacking_evidence()"
```

It must exit 0. The run compiles Mojo through `driver.compile_program`, so it
carries the memslot wrapper (measured peak 0.6 GB; ceiling 8 GB).

## Status

- Open. Depends on `bugs/mid/DIAGNOSTICS_binding_deferrals-part2-part1.md`.
