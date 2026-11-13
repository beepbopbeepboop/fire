# SUITE: `test_comptime_bracket_params.py` asserts a refusal message that no longer exists

**Symptom:** the test is red on master (2026-11-13, `ae5362d4b`) and is not in
`tools/suite.py`, so the gate does not see it:

    $ python3 test_comptime_bracket_params.py
    FAIL  paramless bracket refused (not 0)  cannot compile in-process: a bracketed call a[...]() needs the
          generic instantiated, which the single-unit path does not do; link mode (fire build) does
    Results: 5 passed, 1 failed

**Cause:** commit `45e8d6280` ("codegen: the mutual-recursion refusal fires on a
progressing index, not on 'not a type'") split the refusal into two messages in
`mojo/backend_gimple/emit_calls.py` (~line 3411 and ~3423) and the paramless
bracket call now takes the second one:

    ... the single-unit path does not do; link mode (fire build) does

The test at `test_comptime_bracket_params.py:218` still requires the old
substring `"link-mode specialisation"`.

**Expected:** the test pins the behaviour, not the prose. Accept either of the
two messages, or recompute the expected spelling from the emitted message.

**Exact next step:** change the assertion in
`test_comptime_bracket_params.py::test_paramless_function_bracket_refused_in_single_tu`
to match the current message (e.g. accept `"link mode (fire build)"`), run
`python3 test_comptime_bracket_params.py` (expect 6 passed), and consider
registering the file in a bucket — it is currently ungated, which is why this
rot went unnoticed.
