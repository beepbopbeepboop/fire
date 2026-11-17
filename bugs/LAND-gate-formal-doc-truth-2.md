# Land: should finished branch bug-gate-formal-doc-truth-2 land?

**Branch:** `work/bug-gate-formal-doc-truth-2` (task `bug-gate-formal-doc-truth-2`; its tip is also saved as `refs/archive/work/bug-gate-formal-doc-truth-2`, so dropping it loses nothing).
**Age:** last commit 2026-11-16, first unlanded commit 2026-11-15; 3 commit(s) ahead of master, 1195 behind it; task started 2026-11-16 22:17:36
**Original work:** An earlier attempt left 2 commit(s) on branch work/bug-gate-formal-doc-truth, which you start from. Read `git log master..HEAD` and `git diff master...HEAD` first. Fix the bug in bugs/gate-formal-doc-
**Original claims:** bug:gate-formal-doc-truth

This branch holds finished work that is not on master, and nothing is landing or continuing it. Sort it out:
decide what it is worth now, then act on the decision. Use your judgment; landing is one outcome of three.

Assess first (record the findings in Status):
- Does the branch's own test still fail on master and pass on the branch? If master already passes it, the bug
  may be fixed another way.
- Does master now solve the same problem differently or better (same files rewritten, the doc's subject gone,
  the function replaced)? Then the branch is obsolete.
- Is the change still correct and wanted against today's master, or was it written for a design that moved on?
- How stale is it, and how much of it merges cleanly?

Then do ONE of:
- **LAND**: start from master, bring in the NEWEST branch named in Status (`git merge <it>`, or cherry-pick), resolve
  conflicts keeping both sides' intent, make the result coherent, run the narrow tests that cover the files
  involved plus the branch's own tests, and commit.
- **ADAPT**: land only the part that is still right, rewritten against master, and say what you left out and why.
- **DROP**: land nothing. The reason goes in the commit message that deletes this doc.
In every case, `git rm` this doc in your commit (then `python3 tools/dangling_doc_refs.py --ratchet`). If the
original bug is still open, leave its own doc alone.

## Done when

A commit exists that records the decision: the change (LAND/ADAPT) or the reason it was dropped
(DROP), and this doc is gone.

## Status
- 2026-11-17 04:32:45: conflicts with master (last commit 2026-11-16, first unlanded commit 2026-11-15; 3 commit(s) ahead of master, 1195 behind it; task started 2026-11-16 22:17:36)
  Branch: work/bug-gate-formal-doc-truth-2
  Conflicting files: FORMAL.md, build_stdlib_dylib.py, formal/build.py, formal/model/builtins.py, test_runtime_header_scan.py
- 2026-11-17 04:59: assessed; decision DROP — every one of the branch's 3 commits is
  already on master, and the one still-distinct piece (its census re-sync) is stale.
  Branch: work/bug-gate-formal-doc-truth-2 (tip 73cbb4d6f, 1195 behind master; tip kept
  at refs/archive/work/bug-gate-formal-doc-truth-2)
  * Does the branch's own test still fail on master and pass on the branch? NO —
    all of its tests pass on master, which is where its fixes now live:
    - de7c6f5d2 (parser: terminate the bracket-default sub-stream with EOF, the
      unbounded _parse_primary loop) landed on master as d7067e347; its regression
      test test_string_default_ends_its_sub_stream is in master's
      test_new_syntax_parsing.py (157 passed, 0 failed, measured 2026-11-17).
    - 1da620e5e (memcap/memslot: measure phys_footprint, not RSS) landed on master
      as 9fe0a5c51 (edcdda146 re-measured the suite's memory classes for it); the
      branch tip's tools/procrun.py, tools/memcap.py and test_procrun.py are
      byte-identical to master's (test_procrun.py 22/22, measured 2026-11-17).
    - 73cbb4d6f (re-sync the ABI census 931/425/821 -> 932/426/822 and re-enable
      both census jobs) is superseded: master re-synced the same drift in
      51ce6283b and has since moved further — FORMAL.md now publishes 947 entry
      points / 435 word-shaped (45.9%) against the branch's 932 / 426 (45.7%), and
      the ladder rungs have passed the branch's 822 rung (822->826->829->...).
      Both jobs are registered in tools/suite.py without a disabled= marker, and
      their test files pass on master (test_formal_doc_truth.py PASS=454 FAIL=0,
      test_runtime_header_scan.py 84 passed 0 failed, measured 2026-11-17).
  * Does master now solve the same problem differently or better? YES — the same
    three fixes, landed by other commits, with a newer census.
  * Is the change still correct and wanted against today's master? NO — merging or
    cherry-picking the tip would REGRESS the census (947 -> 932) and re-add the
    stale 822 ladder rung and the pre-932 quoted figures in FORMAL.md,
    formal/build.py, formal/model/builtins.py, build_stdlib_dylib.py and
    test_runtime_header_scan.py (the 5 conflicting files), while losing 1195
    commits of master's other work in tools/suite.py and fire_compiler.py.
  * The branch's deletions of the gate docs are stale: bugs/gate-rthdrscan.md is
    retired on master (6cd1368ca), and bugs/gate-formal-doc-truth.md was re-filed
    on master (b3fe558b2) when the gate went red again on another branch — the
    original bug is tracked there, and per this doc's rule its own doc stays.
  * Staleness/merge: 1195 commits behind; the 5 files above conflict; nothing of
    the branch is worth landing.
  Decision: DROP. Land nothing; the tip stays in refs/archive/work/bug-gate-formal-
  doc-truth-2. The closing commit deletes this doc and adds the pin
  test_regress_land_gate_formal_doc_truth_2.py, which fails while the doc is in the
  tree and passes once this decision is recorded.
