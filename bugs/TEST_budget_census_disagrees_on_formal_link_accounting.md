# TEST: the budget census says 2 for `test_formal_link_accounting.py` and the walk finds 4

**Status: open, found 2026-10-09, not fixed here** (it is a formal-lane change and
this session's claim is `perf:measure-unmeasured`). One-line red in
`test_suite.py`, pre-existing on this branch's HEAD — reproduced with HEAD's own
`test_suite.py`, so it is not something a merge into this branch introduced
today.

## What was run and what it said

    $ python3 test_suite.py
    ...
    FAIL  budgets: the residue census is the residue: the census and the walk
          disagree. ... Difference: test_formal_link_accounting.py: census 2 vs
          walk 4 | census-only:

Everything else in that file passes (362 passed, this 1 failed).

## Why

`STALE_PER_CHILD_BUDGETS` in `test_suite.py` is the census of per-child
`timeout=<int>` literals that are deliberately still literals; the check walks
every `test_*.py` and compares. Two literals were counted; there are four:

    test_formal_link_accounting.py:1083  timeout=600   fire.py build (compile)
    test_formal_link_accounting.py:1097  timeout=600   fire.py build (compile)
    test_formal_link_accounting.py:1147  timeout=600   fire.py build (compile)
    test_formal_link_accounting.py:1156  timeout=120   the built image itself (run)

The first three are in `test_the_audit_is_silent_on_a_sound_image`, the fourth in
`test_raise_flushes_stdout`. The file's last change before this was
`515fe237` ("formal: a NUMBER `printf` conversion of a CONTAINER is refused...")
via the `work/merge-formal8-oct7` merge, which added the two `raise`/`return`
cases — and with them the fourth literal — without adding the census row.

## Expected

Either the census row becomes `4`, or the file is converted to `exec_budget`
(three `COMPILE_TIMEOUT_S`-class budgets and one `RUN_TIMEOUT_S`) and its row is
dropped. The second is what the parent doc asks for per file, with the argv at
the call read to decide which constant — which is the whole point of the
per-file rule and is why this is not a mechanical bump.

The choice matters more than it looks: line 1156's `120` is the child's RUN
budget and the three above are COMPILATION budgets, so a file-wide substitution
would put the wrong constant on three of the four, and the failure mode of that
is a formal job killed at a budget meant for something else.

## Next step

Read the four ARGVs, add `from exec_budget import ...` (or name each site as
deliberate with the reason at the declaration), then drop or update the census row
in `STALE_PER_CHILD_BUDGETS` and re-run `python3 test_suite.py`. The parent doc is
`bugs/TEST_stale_per_child_timeout_literals.md`, whose "next step" already orders
this work per file in the owning lane; this entry is the one file in it whose
census has drifted from its source.