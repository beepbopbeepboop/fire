# SUITE: test_coro_paramflow_cycle.py is in no registered spec

Found 2026-11-22 while checking the `test_suite.py` self-test on the gimplegenerators fix.

## What I ran

    python3 test_suite.py

On HEAD (before the gimplegenerators fix) it reports `Results: 505 passed, 5 failed`; one of the
five is `the estate: every test file is run by something, or says why not`, naming
`test_coro_paramflow_cycle.py` as "not run by any registered spec, not in UNREGISTERED, and in no
declared family". The test was added by `492d9fffd` (coro: a pass-through cycle nothing feeds is
not a generator source) and was never registered in `tools/suite.py`.

## Expected

The test runs in a bucket (it is a fast, pure-parser test; `check` is the natural home), so the
regression for the cycle fix is run by every gate, not only when someone runs it by hand.

## Done when

    python3 tools/suite.py --list | grep coro-paramflow-cycle     # a job in `check`
    python3 tools/suite.py coro-paramflow-cycle                   # 2/2 PASS
    python3 test_suite.py                                         # the estate line
                                                                  # no longer names this file

The last line still lists `test_bootstrap_stage2_dumps_t_print.py` and
`test_type_lattice_predicates.py` for the same reason this file was named;
those two arrived in other landings and are a separate doc, not this one.

## Next step

Register `test('coro-paramflow-cycle', [PY, 'test_coro_paramflow_cycle.py'], ...)` in `tools/suite.py`
in the bucket the other coro parser tests use, with `extra=` naming `mojo/middle/coro.py` and
`fire_compiler.py`, then re-run `python3 test_suite.py` and confirm the estate check passes. This was
left alone because the rules for the gimplegenerators worker say not to register anything outside
its task.
