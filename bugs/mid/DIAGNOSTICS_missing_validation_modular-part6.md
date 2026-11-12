# DIAGNOSTICS_missing_validation_modular part 6: interpreter `constrained[...]()`

Part 6 of the split of `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`.
This is the "non-gimple/formal backends" item in the umbrella's Status: the
gimple backend diagnoses `constrained`, the interpreter does not know the
builtin at all.

## Why this part

The gimple path rejects a provably-false `constrained` at compile time
(`constraint failed: <msg>`, with `test_constrained_diagnostic.py` as the
regression). On the interpreter path the same program does not reach any
constraint logic:

    $ python3 fire.py run constrained_false.mojo
    NameError: name 'constrained' is not defined

Measured 2026-11-10 with

```mojo
fn f():
    constrained[1 == 2, "bad"]()
fn main():
    f()
```

`python3 fire.py run` exits 1 with `NameError` and a traceback, not
`constraint failed: bad`. The true form `constrained[True]()` fails the same
way, so even valid programs using the builtin cannot run under the interpreter.
The parser produces a `CallExpr` whose `func` is a `SubscriptExpr` over
`IdentExpr('constrained')`; `myinterpreter.py` has no case for it.

## Scope

`myinterpreter.py` (the `constrained` call path):

- recognise a call whose `func` is `SubscriptExpr(obj=IdentExpr('constrained'))`
  (the bracket form `constrained[cond, msg]()`), evaluate the first bracket
  argument, and:
  - if it is false, raise `RuntimeError("constraint failed: <msg>")` (or
    `constraint failed` when no message) so `fire.py run` exits nonzero with
    the same wording the gimple path uses;
  - if it is true, return `None` (the builtin has no value);
  - if evaluation raises `NameError`/another error, propagate it; an unknown
    condition must not be treated as false.
- Handle the parenthesised form only if the parser represents it the same way;
  do not add a second parser representation for it.
- Do not try to make the interpreter a compile-time checker. Evaluating the
  condition in the interpreter and failing at run time is the interpreter's
  contract; the observable is the same diagnostic text and a nonzero exit.

## Acceptance

Add `test_interpreter_constrained_diagnostic.py` beside
`test_interpreter_assert_message.py`, using `python3 fire.py run <temp file>`:

| source | expected |
|---|---|
| `constrained[1 == 2, "bad"]()` in `main` | exit nonzero; stderr contains `constraint failed: bad` |
| `constrained[1 == 1, "ok"]()` | exit 0; no `constraint failed` |
| `constrained[False]()` | exit nonzero; stderr contains `constraint failed` |
| `constrained[False, "bad"]()` inside a helper called from `main` | nonzero; `constraint failed: bad` |

Run only:

    python3 test_interpreter_constrained_diagnostic.py
    python3 test_myinterpreter.py

No suite registration and no compile step.

## Status
- **Open.**
