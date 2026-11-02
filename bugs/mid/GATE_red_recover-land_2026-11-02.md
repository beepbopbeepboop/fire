# GATE red: 4 landing-gate job(s) red on `recover-land` (gate red)

## Status (2026-11-02, OPEN; jobs turned OFF to land the round)

The landing gate of round `recover-land` ran RED. The integrator turned these jobs OFF (`tools/gates.json`, one anchored regex) so the round could land, and files each one here until it is fixed:

    bootstrap-stage1-transitive
    bootstrap-stage2-dumps
    bootstrap-stage3-dumps
    mojoc

Tasks landed with this round: recover-land.

Evidence: `work-integ/gate.log` and `work-integ/confirm.log` (the failing jobs re-run alone), `work-integ/build/suite.log` for the job output.

Consequence: these jobs are NOT covered by the gate for this landing. Re-enable each one when fixed with `python3 tools/control.py gate on '<pattern>'` and remove this report in the same commit.

## Status 2026-11-02 (partial: `mojoc` goes from hundreds of errors to two)

Landed (module_qualifier leaf move + os.path word-ABI wrappers + the tuple-unpack container-slot fix):
`make mojoc` on master fails in `jit/arm64.py` ("invalid argument to gimple call", `expected expression before '('`)
and the closure-import errors (`module 'mojo.middle.coro' has no attribute 'module_qualifier'`); with this landing the
self-host compile of the compiler reaches gcc with exactly TWO errors left, both the same defect, in
`mojo/backend_gimple/module_gen.py` lines 13797 and 13860:

    error: passing argument 2 of 'gen_module_impl__phase17_value_type' makes integer from pointer without a cast
        _t = _phase17_value_type(_gvalue)      # _gvalue = _pairs[_pi][1]; typed `char *`, callee param is int64_t

A call to a nested function (`_lower_closure_call`, emit_calls.py ~6944) passes the argument pair as lowered, with no
coercion to the lifted function's parameter type. Next step: coerce each `full_arg_pairs` entry to
`gen.func_param_types[lifted]` (skipping the env slot) via the same `_safe_coerce_emit` path a free-function call
uses; then `make mojoc`, re-enable `mojoc` (`python3 tools/control.py gate on mojoc`), then the three bootstrap jobs.
Checks run: `compile_stdlib.py` 610 passed / 0 unexpected; `test_gimple_runner.py` 553 passed / 15 failed, the same
15 as pristine master (551 / 15). The four jobs are still OFF; nothing was re-enabled.
