# `test_suite.py` self-test: `test_trait_generic_method_alpha_rename.py` is run by nothing

**Found by:** the `bug:gate-rthdrscan` lane (2026-11-14), running
`python3 test_suite.py` — a file this lane touched, so it ran the whole file.
**Not caused by that lane:** `tools/suite.py` on master (`d3ec70ee7`) has no
mention of the test, and this branch does not register or remove one.

## What I ran

    python3 tools/memslot.py --gb 8 --label testsuite -- python3 test_suite.py

## What I saw

    Results: 415 passed, 3 failed
      - the estate: every test file is run by something, or says why not: not
        run by any registered spec, not in UNREGISTERED, and in no declared
        family: test_trait_generic_method_alpha_rename.py

The file was added by `3b7b3d6ef` ("elaborate: a method's own bracket params
are alpha-renamed in its signature") together with its behaviour, and the
commit registered nothing in `tools/suite.py`. `git show d3ec70ee7:tools/suite.py
| grep -c trait_generic_method_alpha` is `0`, so master's own gate is red on
this row today: the test exists to pin landed behaviour and no gate runs it.

## What I expected

Every `test_*.py` is either a registered spec (in a bucket), or named in
`UNREGISTERED` with a reason. This one is neither, which is the coverage hole
`test_suite.py`'s estate check exists to catch.

## Exact next step

Register it beside the other per-bug pins in `tools/suite.py` (the `reg-*`
block that starts at `reg-elaboration-recursion-diagnostic`), mirroring
`reg-gate-rthdrscan`, and add the job name to the `'regressions'` bucket list
in the same file:

    test('reg-trait-generic-method-alpha-rename',
         [PY, 'test_trait_generic_method_alpha_rename.py'], mem='tiny',
         desc='per-bug regression pin (elaborate: bracket params alpha-renamed)')

then re-run `python3 test_suite.py` and confirm the estate row is gone. If the
test is too expensive to run every gate, add it to `UNREGISTERED` in
`test_suite.py` with the reason instead — but do not leave it in neither.
