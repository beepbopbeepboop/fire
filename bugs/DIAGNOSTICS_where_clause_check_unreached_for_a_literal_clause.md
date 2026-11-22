# DIAGNOSTICS: a literal `where x < 2` gets the backend's wording while the alias spelling gets the elaborate check's

**Area:** `monomorphize.instantiate` -> `elaborate.check_where_clauses`.
**Where the branch shows:** the registered job `reg-where-alias-diagnostic`
(`python3 test_where_alias_diagnostic.py`) fails one case,
`test_integer_literal_where_still_enforced`, which requires
`requirement 'x < 2' is not satisfied`.

## What is NOT the cause (measured)

The folder is fine, and it takes a parsed NODE, not source text:

```
node = Parser(py_tokenize('var y = x < 2')).parse_module()[0].value
#   BinaryOp(op='<', left=IdentExpr('x'), right=IntLiteral(2))
eval_const_bool_state(node, {'x': 5})   -> 0    # CONST_FALSE
eval_const_bool_state(node, {'x': 1})   -> 1    # CONST_TRUE
```

and the elaborate entry point raises exactly what the test wants:

```
elaborate.check_where_clauses(mod, tpl, {'x': 5})
    -> WhereConformanceError: requirement 'x < 2' is not satisfied
elaborate.check_where_clauses(mod, tpl, {'x': 1})   -> accepted
```

An earlier probe passed the condition as a STRING (`eval_const_bool_state('x < 2',
...)`) and read `-1`; `_const_foldable` walks node shapes, so a string is simply
not foldable. That was the probe's error, not the folder's.

## What IS observed

Per-case, `test_where_alias_diagnostic.py` (8 pass, 1 fails):

```
PASS test_function_where_alias_violated_fails   (wants "requirement 'x < LIMIT' is not satisfied")
PASS test_struct_where_alias_violated_fails
FAIL test_integer_literal_where_still_enforced   (wants "requirement 'x < 2' is not satisfied")
PASS test_unfolderable_alias_clause_stays_accepted
```

The check IS wired into the compiler in two places: `monomorphize.instantiate`
(`elaborate.check_where_clauses('', template_src, type_args or {})`, visible as
`fire.ci`'s `elaborate_check_where_clauses_4d4627`) and
`module_gen._check_fn_signature_binding_violations`
(`check_where_clauses(module_src, tmpl, targs)`). Neither is on the obvious
`f[5]()` call path, and the one that passes a real `module_src` only runs for a
generic-struct mention in a signature -- so what produces the alias case's
string is NOT yet pinned down. It is only established that the alias case's
expected text IS in its output and the literal case's is not.

The refusal the literal case does get is the GIMPLE backend's
(`invalid call to 'f': violated constraint`, plus the note `expected '(x < Int(2))'`)
-- which is modular's own wording (`mojo/lib/MojoParser/Constraints.cpp`:
`diag << "violated constraint"`).

## Two readings, and the step that decides them

1. The check is not reached for a clause over a bound parameter and a literal.
   First pin down what emits the alias case's text (grep the output of
   `build_refusal` for it and break on `elaborate.py:2913` under a debugger);
   then compare the bindings each path hands the folder. `f[5]` passes `5` as a
   COMPTIME arg while `instantiate` forwards `type_args`, so `x` may be absent
   from what the folder sees -- which would make it CONST_UNKNOWN (no raise)
   while the alias case still resolves `LIMIT` from the module source.
2. The test's expectation is the driver/stage2 wording, and the Python path is
   meant to say `violated constraint` -- in which case this case should assert
   that. `test_binding_deferral_diagnostic.py` asserts BOTH strings through
   `driver.compile_program` and passes, so it is the model for what a single
   refusal may carry.

Either way `test_integer_literal_where_still_enforced` is the case to fix, and
`python3 test_where_alias_diagnostic.py` should end at 9/9.
