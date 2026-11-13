# DIAGNOSTICS_binding_deferrals part 1: a signature binding that violates a struct `where` clause reports `violated constraint`

Parent: `bugs/hard/DIAGNOSTICS_binding_deferrals.md` (SPLIT). This part does
NOT fix the bug end-to-end.

Class: **mid** (this doc lives in `bugs/mid/`). It is not a one-line check: a
function declaration's parameter types are currently only resolved to C types
(`emit_funcs.py::_fixed_param_ctypes` / `_param_struct_name`), and are never
turned into generic instantiations, so the existing check in the body paths
never runs for them. The part has to add a declaration-time binding check that
reuses `elaborate.py`'s parser/constraint code without duplicating it.

## Goal

A function DECLARATION whose parameter type is a generic struct instantiation
whose `where` clause is provably false for the written type arguments fails to
compile with modular's wording, `error: violated constraint`, and with no
second diagnostic.

Modular source (`mojo/test/mojo-parser/failed_binding_deferrals.mojo`, lines
30-35):

```mojo
# CHECK: [[@LINE+3]]:{{[0-9]+}}: error: violated constraint
# CHECK-NOT: error:
def failed_binding[U: Movable & Deinitable](
    x: NeedsCopyablePos[CondCopyable[U], 0]
):
    pass
```

The `where n > 0` clause of `NeedsCopyablePos` is provably false at `n == 0`,
so this declaration must be rejected even though no call instantiates it.

**Measured 2026-11-12 on this tree:** compiling the whole modular file through
`driver.compile_program` succeeds (`Built: ...`, `COMPILED OK`, 0.4 GB peak) —
neither declaration is checked. The earlier landed fixes (`22dfa22c4`,
`a5daccf4e`) validate a BODY instantiation (`var a = NeedsCopyablePos[..., 0]()`)
and pass `test_binding_deferral_diagnostic.py`, but a signature annotation is
never instantiated, so the check is never reached.

## Scope

1. Add the declaration-time check where a function's parameter annotations are
   first inspected as Mojo types (the signature pass around
   `mojo/backend_gimple/emit_funcs.py::_fixed_param_ctypes`, or the module
   pre-pass in `mojo/backend_gimple/module_gen.py` that runs before signature
   lowering). One hook only; do not add a second parser.
2. Reuse `elaborate.py`: `extract_struct_source` for the template,
   `bind_type_args` for the positional type arguments, and
   `check_where_clauses` for the fold. Do not re-implement clause folding or
   header-text extraction.
3. Only check an annotation that names a generic struct whose source is
   available (defined in this module or a registered imported generic struct),
   and only when `bind_type_args` yields a binding. An annotation this code
   cannot resolve keeps its current accept behaviour.
4. Report a provably false clause with the text `error: violated constraint`
   (optionally followed by a note naming the requirement). Modular's CHECK
   requires that exact adjacency; the body path's
   `error: invalid instantiation of '<name>': violated constraint` does NOT
   contain it. Use the plain signature wording here.
5. Do not report an UNDECIDED requirement in this part — that is part 2
   (`invalid bindings in signature: lacking evidence`). Do not change the body
   instantiation paths or their tests.

## Acceptance

- `def failed_binding[U: Movable & Deinitable](x: NeedsCopyablePos[CondCopyable[U], 0])`
  fails to compile with `error: violated constraint`, exactly one `error:` line,
  and no `lacking evidence` / deferred-constraint text.
- A satisfied signature binding still compiles (e.g.
  `x: NeedsCopyablePos[Int, 1]`), and the existing body-instantiation
  regressions in `test_binding_deferral_diagnostic.py` keep passing.
- No whole-closure compile and no `make gate`: this is a declaration-pass
  change, verified by the one test below.

## Done when

`test_binding_deferral_diagnostic.py::test_signature_failed_binding_reports_violated_constraint`
(added by the 2026-11-12 replan; it currently fails with
`a failed binding in a signature compiled`) passes:

```
python3 tools/memslot.py --gb 8 --label binding-deferral-p1 -- python3 -c "import test_binding_deferral_diagnostic as t; t.test_signature_failed_binding_reports_violated_constraint()"
```

then add the new function to the file's `__main__` list so
`python3 test_binding_deferral_diagnostic.py` covers it too.

## Not in this part

- The `n == 1` "lacking evidence" binding (part 2).
- Body instantiations, already covered by the existing tests.
- Column/line precision beyond what the diagnostic already carries: modular
  pins the line of the parameter annotation; a diagnostic whose text matches
  and that names the annotation is enough for this part, and the part may
  report the `FunctionDef`'s line rather than the parameter's.
