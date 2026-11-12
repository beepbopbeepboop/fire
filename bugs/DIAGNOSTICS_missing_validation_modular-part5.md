# DIAGNOSTICS_missing_validation_modular part 5: interpreter `assert` message

Part 5 of the split of `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`.
The umbrella's Status says the compiled path now prints
`Assert Error: <msg>` (`assert_failure_message.mojo`); this part gives the
interpreter the same observable.

## Why this part

Modular's `test/mojo-integration/assert_failure_message.mojo` is:

```mojo
def main():
    # CHECK: Assert Error: x must be positive
    assert False, "x must be positive"
```

The compiled path prints `Assert Error: x must be positive`. `python3 fire.py
run` (this tree's interpreter) prints:

    Error: /path/assert_failure_message.mojo:20:0: x must be positive

and then a Python traceback. The user message is there, but the required
`Assert Error:` prefix is not, so the modular check fails on the interpreter
path.

`myinterpreter.py::execute_AssertStmt` raises
`AssertionError(f"{loc}{msg}")`. `fire.py`'s top-level handler adds the
`Error: ` prefix when it prints the exception, so adding the `Assert Error: `
prefix inside the raised message is sufficient.

## Scope

`myinterpreter.py::execute_AssertStmt` (around line 6451) only:

- raise `AssertionError` with `Assert Error: <msg>` when a message was
  supplied, and `Assert Error: assert failed` (or the existing default text
  with the prefix) when not;
- keep the existing `file:line:` location prefix;
- do not change the `fire.py run` exit code, the traceback printing, or the
  compiled path's runtime helper. If the traceback is considered noise, it is
  a separate change and not part of this acceptance.

## Acceptance

Add `test_interpreter_assert_message.py` beside `test_myinterpreter.py`. The
test writes a temp `.mojo` file containing the modular snippet, runs it with

    python3 fire.py run <temp file>

and requires a nonzero exit and `Assert Error: x must be positive` in stderr.
Also check that `assert True` exits 0 and prints no `Assert Error`.

Run only:

    python3 test_interpreter_assert_message.py
    python3 test_myinterpreter.py

No suite registration and no compile step (the interpreter runs the source
directly).

## Status
- **Open.**
