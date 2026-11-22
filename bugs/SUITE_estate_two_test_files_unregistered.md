# SUITE: two landed test files are in no registered spec

Found 2026-11-22 with `bug:SUITE_coro_paramflow_cycle_test_unregistered`: that
round registered `test_coro_paramflow_cycle.py` and the same estate line still
named two more files. This is the remainder of that check's output, split out
because the two files arrived in other landings and each belongs to the lane
that wrote it.

## What I ran

    python3 test_suite.py

on `a1fb3ca15` plus the registration commit. The `the estate: every test file
is run by something, or says why not` check reports:

    not run by any registered spec, not in UNREGISTERED, and in no declared
    family: test_bootstrap_stage2_dumps_t_print.py,
    test_type_lattice_predicates.py

Neither is excused, so nothing runs either one except a person typing its
filename. Both fail the "a test file nothing runs is a claim with no evidence"
rule the check exists for.

- `test_bootstrap_stage2_dumps_t_print.py` — added by `0223ef16e` with its fix
  (the `bootstrap-stage2-dumps` fanout skips behind disabled
  `bootstrap-stage2-cc`). It reads `tools/suite.py`'s registry and asserts
  `bugs/mid/gate-bootstrap-stage2-cc.md` still disables the producer, so it is
  three unittest cases at 0.0 GB. `claim:gate:bootstrap-stage2-cc` is the lane
  that owns the subject; whoever deletes that doc must retire this pin too,
  and its cache key would have to name both `tools/suite.py` and the doc.
- `test_type_lattice_predicates.py` — added by the GIR stage 4 landings
  (`6a89c722e`, `cf600c4d5`). Pure Python over `mojo/middle/types.py` and
  `tools/type_string_codemod.py`, no build and no compiler run; the `GIR_W1_*`
  docs run it by name (`python3 test_type_lattice_predicates.py`).

## Expected

Both run in a bucket. `check` is the natural home for both: pure-Python, no
build, no Lean. The alternative — an `UNREGISTERED` entry — would be a
permanent excuse for tests that cost less than the check that measures them.

## Next step

    test('bootstrap-stage2-dumps-t-print', [PY, 'test_bootstrap_stage2_dumps_t_print.py'],
         mem='tiny',
         extra=['test_bootstrap_stage2_dumps_t_print.py', 'tools/suite.py',
                'bugs/mid/gate-bootstrap-stage2-cc.md'])
    test('type-lattice-predicates', [PY, 'test_type_lattice_predicates.py'], cache=True,
         mem='tiny',
         extra=['test_type_lattice_predicates.py', 'mojo/middle/types.py',
                'tools/type_string_codemod.py'])

then add both to `BUCKETS['check']` (the append list at the bottom of
`tools/suite.py`, not the literal) and re-run `python3 test_suite.py` until the
estate line is empty. Do not add them to `UNREGISTERED`: both are green and
cheap, and the GIR docs already treat the lattice pin as run.
