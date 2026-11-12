# DIAGNOSTICS: the removed `fn` keyword is accepted; warn now, refuse once the hits are gone

Status: OPEN, planned work. Filed 2026-11-11 on master. Nothing here is implemented yet.

## What the real compiler does (measured, `tools/mojo build`, 2026-11-11)

    def-less file:  fn f(x: Int) -> Int:
    error: 'fn' has been removed; use 'def' instead

In the toolchain measured here `fn` is already an ERROR, not a warning. Real Mojo refuses it at the keyword, column 1.
Our compiler accepts `fn` silently: `fn f(x: Int) -> Int: return x` compiles.

The project's own note is that `fn` is dead and is going away. This doc is the plan for getting there without breaking
the tests in one step.

## Decided behaviour

1. **Now: warn.** Our compiler emits a warning at every `fn` keyword, at its real location, with the real message:
   `'fn' has been removed; use 'def' instead`. The compile still succeeds, so nothing that works today breaks.
2. **Then: refuse.** Once every hit is gone from the repo and the tests, the warning becomes the real refusal (an error,
   same message, same location). The switch is one commit, and it is the commit that removes the warning path.

## Measured scope of the hits

- `.mojo` files in the repo: 13 files, 18 `fn` lines (`grep -rh '^[[:space:]]*fn ' --include=*.mojo`).
- Test fixtures: 456 Python string constants in 50 `test_*.py` files contain a line starting with `fn `
  (found by parsing each test file's string constants).

These are not all the same kind of hit:

- Ordinary fixtures that use `fn` as a plain spelling of `def`. Change them to `def`. This is most of them.
- Fixtures whose point is the `fn` spelling itself. Examples: `test_out_param_return_type_diagnostic.py`, where the
  `fn` keyword test is an expected failure that pins the refusal. These keep `fn` and are marked as the case that
  tests the keyword.
- Hits in files that are not Mojo at all (a Python test that quotes Mojo in a docstring). Check each one by hand.

## How to find the hits, not just the ones a grep finds

A grep finds `fn` at the start of a line. It misses `fn` after a decorator, inside a string built with `+`, in a
`.md` example, or inside code that is generated. So:

1. Turn the warning on, then run the whole test tree and collect every warning, not just the first.
2. Count the warnings by file. Each file's hits are changed in the same commit as the file's test.
3. Anything the warning does not reach (a path that never calls the lexer) is found by the grep above and the
   measured fixture list, not by guessing.

## Fix order

1. Add the warning path to `fire_compiler.py` (the keyword is seen in the parser), using the real message and the
   token's location. A unit test pins the message and location against the measured output.
2. Run the test tree with the warning on and collect the hits. Record the list in this doc.
3. Change each hit to `def` in the commit that owns its test, or mark it as the keyword test.
4. Once the list is empty, switch the warning to a refusal, and delete the warning path in the same commit.

## Related

- `test_out_param_return_type_diagnostic.py`: the `fn` keyword case, an expected failure today. It becomes a plain
  assertion when the refusal lands.
- `bugs/TEST_out_self_with_return_type_fixtures_are_invalid_mojo.md`: the same family of fixture-validity problem.
