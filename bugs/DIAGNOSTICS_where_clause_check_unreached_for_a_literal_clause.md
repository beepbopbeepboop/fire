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

The mechanism IS pinned. `fire.py build` routes the two spellings through
different engines:

```
literal  -> myinterpreter.check_where_clause: interp.eval_expr(x < 2) folds (x is a
            comptime param in scope) -> _ConstraintViolation -> where_violation_record
            (myinterpreter.py:955) -> "error: invalid call to 'f': violated constraint"
            + "note: constraint declared here evaluated to False, expected '(x < Int(2))'"
alias    -> interp.eval_expr(x < LIMIT) raises (LIMIT is a module-level alias, not in
            the function's comptime scope) -> `except Exception: ok = True` -> the
            clause is left alone -> the call falls through to the compile path, whose
            elaborate check raises WhereConformanceError, surfaced by
            emit_resolve.py:4259 as "note: WhereConformanceError: requirement 'x < LIMIT'
            is not satisfied"
```

So the literal spelling gets the interpreter's wording and the alias spelling gets
the compiler's, for the same construct. The interpreter's is modular's own
(`mojo/lib/MojoParser/Constraints.cpp`: `violated constraint` + the
`constraint declared here evaluated to False, expected <prop>` note), and
`test_static_call_diagnostics.py` pins that wording for `where n > 0`. The
`WhereConformanceError` note is this repo's wrapper leaking.

The alias spelling's output begins `Error building:`, the literal one does not --
so for the alias spelling the interpreter DECLINED the call and `fire.py build`
fell back to the compiler. It is not the `alias` declaration itself: a module
with `alias LIMIT = 2` and a trivial `main` builds cleanly (`Error building`
absent, rc 0). It is the clause evaluation --
`check_where_clause` sets `interp.scope = scope` (the function's comptime
parameters) before `interp.eval_expr(cond)`, and `LIMIT` lives in the MODULE
scope, so the name is not reachable from there and the handler's
`except Exception: ok = True` declines.

Consequence for the test: `test_integer_literal_where_still_enforced` asserts the
COMPILER's wording against the INTERPRETER's output. Its sibling
`test_function_where_alias_violated_fails` passes only because that spelling
happens to reach the compiler.

## The fix, and what it moves

Make the module's top-level names reachable from the scope `check_where_clause`
evaluates in: either give that scope the module scope as a parent, or resolve an
unbound name against the module bindings before the `except Exception` declines
it. Then both spellings stay on the interpreter and get its wording, which is
modular's.

Consequence: the two message-expecting cases in
`test_where_alias_diagnostic.py` (`test_function_where_alias_violated_fails`,
`test_integer_literal_where_still_enforced`) both move to the interpreter's
wording, which is what `test_static_call_diagnostics.py` already pins for
`where n > 0`. The job `reg-where-alias-diagnostic` is green when
`python3 test_where_alias_diagnostic.py` is 9/9.
