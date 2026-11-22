# DIAGNOSTICS: the where-folder cannot fold a comparison whose operands are bound names, so a literal `where x < 2` is refused by the backend with a different message

**Area:** `elaborate.py` (`_check_template_where_clauses` ->
`mojo.middle.comptime.eval_const_bool_state`).
**Where the branch shows:** the registered job `reg-where-alias-diagnostic`
(`python3 test_where_alias_diagnostic.py`) fails its last case,
`test_integer_literal_where_still_enforced`, which requires
`requirement 'x < 2' is not satisfied`.

## Measured (this tree)

```
python3 -c 'from mojo.middle.comptime import eval_const_bool_state;
            print(eval_const_bool_state("x < 2", {"x": 5}))'
-1                       # UNDECIDED
```

`-1` is `UNDECIDED`, not `CONST_FALSE`. The same probe for the alias spelling is
also `-1`:

```
eval_const_bool_state('x < 2',   {'x': 5})            -> -1
eval_const_bool_state('x < LIMIT', {'x': 5, 'LIMIT': 2}) -> -1
eval_const_bool_state('x < 2',   {'x': 1})            -> -1
```

So `_check_template_where_clauses` takes its `undecided` branch and never
raises `WhereConformanceError`, and the refusal the caller sees comes from the
GIMPLE backend's own check instead (`mojo/backend_gimple/emit_resolve.py`,
`invalid call to '<fn>': violated constraint` plus the note `constraint declared
here evaluated to False, expected '(x < Int(2))'`).

Control, running each case of `test_where_alias_diagnostic.py` with
`unknown_decl_check._alias_value_ids` disabled and enabled:

```
control (fix disabled):  7 passed, 2 failed
with the fix:            8 passed, 1 failed
```

The one remaining failure is `test_integer_literal_where_still_enforced`, which
fails in BOTH states -- it is not caused by the alias fix
(`unknown_decl_check.py`) and is not affected by it.

## Why this is not a wording dispute

`emit_resolve.py` documents its message as modular's
(`mojo/lib/MojoParser/Constraints.cpp`: `diag << "violated constraint"`, with the
note `constraint declared here evaluated to False, expected <prop>`), so the
backend's text is right. The test's expectation
(`requirement 'x < 2' is not satisfied`) is the message
`elaborate.py:2913` raises when the folder CAN fold the clause. The defect is
that the folder cannot fold it, not that either message is wrong.

## Expected

`eval_const_bool_state('x < 2', {'x': 5})` returns `CONST_FALSE` (and
`{'x': 1}` returns `CONST_TRUE`), so the elaborate path raises
`requirement 'x < 2' is not satisfied` as the test expects. Add the case to
whatever covers `eval_const_bool_state` (a comparison between a bound name and a
literal), and re-run `python3 test_where_alias_diagnostic.py` -- all nine cases
should pass, which is also what clears the alias hard-error doc.
