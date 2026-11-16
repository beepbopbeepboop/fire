# SUITE_estate_two_unregistered_tests_2026-11-15: two test files landed with no spec, so the estate row is red again

## Symptom

`python3 test_suite.py` on master `f7169febf` (2026-11-15) reports:

    Results: 424 passed, 4 failed
      - the estate: every test file is run by something, or says why not:
        not run by any registered spec, not in UNREGISTERED, and in no
        declared family: test_signature_bound_evidence_diagnostic.py,
        tools/test_gate_files.py

The other three FAIL lines in that run are the separate, already-filed gate
ledger state (`disabled:` rows for `gimple`/`metalgpu`/`stdlib-syntax`) and a
stale `bugs/OPEN_WORK.md` generated block from the `FORMAL_arm64_instruction_coverage-part*`
docs. This doc is only about the estate row.

## What I ran

    python3 tools/memslot.py --gb 8 --label suite-self-test -- python3 test_suite.py

## Where the two files came from

- `test_signature_bound_evidence_diagnostic.py` landed in `a42af8658` and was
  integrated by `22e2c014e` ("integrate bug-gate-mojoc") with no
  `tools/suite.py` registration.
- `tools/test_gate_files.py` landed in `586460016` ("integrate: a red-on-master
  job is forgiven only for the files master also fails") with no registration.

Neither is in `UNREGISTERED` and neither is covered by a `_DECLARED_BY_RULE`
family, so the estate check names both.

## What I expected

No estate FAIL line: every `test_*.py` / `*_test.py` is run by a registered
spec, listed in `UNREGISTERED` with a reason, or covered by a declared family.

## Exact next step

Register each file in `tools/suite.py` (the cheap, git-free ones belong in a
bucket that a gate reaches; the same decision the land-doc registration made):

1. `test('signature-bound-evidence-diagnostic', [PY, 'test_signature_bound_evidence_diagnostic.py'], mem='tiny', ...)`
   with a `desc=` and a bucket. It is a compiler-diagnostic pin, so `check` if
   it is sub-second with no build, otherwise `regressions`.
2. `test('reg-gate-files', [PY, 'tools/test_gate_files.py'], mem='tiny', ...)`
   in `regressions` beside the other `reg-*` pins; its subject is
   `tools/integrate.py`'s `failing_files()`, so say so in the `desc=` and add
   `extra=['tools/test_gate_files.py', 'tools/integrate.py']` if it is cached.

Then `python3 test_suite.py` should have no estate FAIL line. Do NOT add them to
`UNREGISTERED`: both are cheap in-process checks, which is the case CLAUDE.md's
cost rule says wants a bucket rather than an excuse.

Filed by the `bug:SUITE_test_land_doc_unregistered` worker, which hit this while
running the required quick test for its own estate fix. It is outside that
task's area and not fixed there.
