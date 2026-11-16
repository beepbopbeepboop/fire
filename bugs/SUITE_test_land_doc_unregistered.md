# SUITE_test_land_doc_unregistered: `tools/test_land_doc.py` is in no spec, no `UNREGISTERED` entry, and no declared family

## Symptom

`python3 test_suite.py` (the `suite-self-test` job, `tiny`, ~70 s) reports:

    Results: 424 passed, 1 failed
      - the estate: every test file is run by something, or says why not:
        not run by any registered spec, not in UNREGISTERED, and in no declared
        family: tools/test_land_doc.py

The other 424 checks pass, including the per-child-budget census once this
session's own files adopted `exec_budget`'s constants.

## Measured (2026-11-15, HEAD `fa105c747`)

`git log --oneline -2 -- tools/test_land_doc.py` gives `62411916c` and
`3cd47cd36` ("integrate: a branch that cannot land gets a
`bugs/LAND-<root>.md` doc workers can carry across time"), so the file landed
with the land-doc feature and was never entered in `test_suite.py`'s estate
inventory. It is a real, cheap unit test:

    python3 tools/test_land_doc.py

It mocks `control.MAIN` into a temp dir and exercises `integrate`'s land-doc
create/append path — no compiler, no build, no git.

## Expected

`python3 test_suite.py` reports no estate failure: every `**/test_*.py` /
`**/*_test.py` file is either run by a registered spec, listed in
`UNREGISTERED` with a reason, or covered by a `_DECLARED_BY_RULE` family.

## Exact next step

Pick one, in `test_suite.py` (where the inventory lives):

1. Register it, e.g. `test('land-doc', [PY, 'tools/test_land_doc.py'],
   mem='tiny', cache=True, extra=['tools/test_land_doc.py',
   'tools/control.py', 'tools/integrate.py'], ...)` and put it in a bucket
   (`check` or `check-orchestrator` — it is a git-facing fleet pass, so
   `check-orchestrator` matches the bucket's stated scope); or
2. add `'tools/test_land_doc.py': _STANDALONE_TEST_REASON` (or a specific
   sentence) to `UNREGISTERED`, if the LAND lane is expected to run it by hand.

Either way the doc disappears with the fix, per the bug-doc policy.

Filed by the GPU offload replan worker: it is outside that task, hit while
running the suite self-test, and not fixed there.
