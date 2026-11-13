# TEST: `test_comptime_bracket_params.py` asserts a refusal message the code no longer prints

**Job:** none — the file is not registered in `tools/suite.py`, so no bucket runs it. It is red when
run directly (`python3 test_comptime_bracket_params.py`), which is how it was found while verifying the
`stdlib-syntax` fix; a stale assertion in an unregistered test is a coverage hole, not a gate red.

**Measured on master `b099ff00` + the 2026-11-13 `stdlib-syntax` fix, 2026-11-13:**

    python3 test_comptime_bracket_params.py
    # 5 passed, 1 failed
    # FAIL  paramless bracket refused (not 0)
    #   cannot compile in-process: a bracketed call a[...]() needs the generic
    #   instantiated, which the single-unit path does not do; link mode
    #   (fire build) does

The behaviour is correct — `a[T: Int]()` in the single-TU path is refused — but the assertion is

    check("paramless bracket refused (not 0)",
          "link-mode specialisation" in str(e), detail=str(e))

and `_lower_call` (`mojo/backend_gimple/emit_calls.py`, the
`cannot compile in-process: a bracketed call …` block) says "link mode (fire build) does", not
"link-mode specialisation". The same failure reproduces with the whole of `emit_calls.py` reverted to
`b099ff00`, so it is not caused by a recent codegen change: the test has been asserting a phrase the
producer does not print.

**Exact next step:** make the two agree. Either change the assertion to a phrase the refusal already
contains (`"needs the generic instantiated"` / `"link mode (fire build)"`), or restore
"link-mode specialisation" to the message — prefer the assertion, because the message's current wording
names the command a user should run. Then `python3 test_comptime_bracket_params.py` must be
6 passed. Separately, this file (and `test_elaboration_recursion_diagnostic.py`) is in no bucket, so
nothing in `make check`/`make gate` can observe it either way; decide whether it belongs in `regressions`
before relying on it as coverage.
