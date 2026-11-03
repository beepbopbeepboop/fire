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

## Status 2026-11-02 (later: `mojoc` builds; the binary then crashes)

The two remaining gcc errors are fixed. Cause: a lifted closure registers its parameter types
(`func_param_types`) only when its OWN body is generated, and the parent generated its nested closures in plain
name order, so `_phase17_scan_if_branches` / `_phase17_scan_try_branches` (which sort before the helper they call)
were lowered before `_phase17_value_type` had a registered signature and passed a `char *` into its `int64_t`
parameter. `module_gen._gmi_closures_callee_first` now generates a sibling that another sibling calls first (name
order otherwise, a cycle falls back to name order); the three identical inline `sorted(...)` sites share it.
`make mojoc` now completes with 0 gcc errors. `compile_stdlib.py` 610 passed / 0 unexpected;
`test_gimple_runner.py` 554 passed / 15 failed, the same 15 as pristine master.

`mojoc` is re-enabled in THIS doc's OFF entry (`tools/gates.json`). It is still named by the separate underscore
entry (`GATE_red_recover_land_2026-11-02.md`, the 23-job one), which another worker holds; turn it on there with
`control.py gate on` when that doc lands.

NEXT (the real remaining blocker for the three bootstrap jobs, which stay OFF): the built binary segfaults on the
simplest use, `./mojoc FILE.py --dump` on a 20-line program: `EXC_BAD_ACCESS (address=0x9)` in `mojo_dict_len`
(the `-O2 -g0` binary gives lldb a single frame). That is the corrupt-dict-value class recorded in CLAUDE.md's
DEBUGGING METHOD. Next step: build with `-g` frame pointers (`MOJO_OPT`), get the caller chain, and bisect the dict
whose value is a non-dict. The earlier unpack fix (a list slot returns its own word) is a plausible neighbour, not a
confirmed cause: master's `mojoc` never built, so there is no baseline binary to compare against.
