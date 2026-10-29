# CODEGEN: `case C():` class patterns are not type tests

Found while planning `bugs/COMPILE_FAIL_Tools_cases_generator_analyzer.md` (2026-10-29).

## What I ran

```python
class Op:
    def __init__(self, n: int):
        self.n = n

def f(x: Op) -> int:
    match x:
        case Op():
            return 1
        case _:
            return 0

print(f(Op(3)))
print(f(3))
```

`python3 fire.py run` on this file, HEAD `33f0a49b0`:

```
TypeError: __init__() missing required argument: 'n'
  ... myinterpreter.py execute_MatchStmt: if self.eval_expr(pattern) == subject:
```

## Expected (CPython 3.14)

```
1
0
```

`case Op():` is a TYPE TEST: `isinstance(subject, Op)`. It does not construct `Op`.

## Why it is a silent miscompile, not only a crash

`execute_MatchStmt` evaluates the pattern as an expression and compares it with
`==`. For a zero-argument class that constructs a fresh instance and compares it
against the subject, so `case Op():` is never a type test, and the result depends on
`__eq__` and not on the subject's class. The crash above is the only visible symptom
because `Op` happens to require an argument.

## Compiled path

`mojo/backend_gimple/emit_stmts.py` `_gen_stmt_MatchStmt` refuses class patterns by
name (`formal/model.py` `MATCH_REFUSED_KINDS`, kind `"class pattern"`). That refusal is
deliberate and its text is correct; it is the reason the compiled path does not
silently miscompile. The interpreter has no such refusal, which is the divergence.

## Next step

Implement CPython's class-pattern semantics on both paths, as planned in
`bugs/COMPILE_FAIL_Tools_cases_generator_analyzer.md` ("Plan", steps 1-3):

- `case C():` → `isinstance(subject, C)`.
- `case C(x)` → `isinstance` plus the positional sub-pattern against
  `C.__match_args__[0]`. A class without `__match_args__` raises CPython's TypeError.
- Keyword sub-patterns (`C(x=0)`) stay refused on the compiled path.

Regression test: `test_match_class_pattern.py` (to be added), expected output from
CPython 3.14, run through BOTH `fire.py run` and `fire.py build`. It must FAIL on the
interpreter today.
