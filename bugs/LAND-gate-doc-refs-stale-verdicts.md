# Land: should finished branch fix-proof-bug-gate-doc-refs-stale-verdicts land?

**Branch:** `work/fix-proof-bug-gate-doc-refs-stale-verdicts` (task `fix-proof-bug-gate-doc-refs-stale-verdicts`; its tip is also saved as `refs/archive/work/fix-proof-bug-gate-doc-refs-stale-verdicts`, so dropping it loses nothing).
**Age:** last commit 2026-11-20, first unlanded commit 2026-11-19; 2 commit(s) ahead of master, 67 behind it; task started 2026-11-20 01:40:41
**Original work:** Branch work/bug-gate-doc-refs-stale-verdicts (a finished worker branch; original task: Fix the bug in bugs/gate-doc-refs-stale-verdicts.md at its ROOT CAUSE. Read the doc's Status/next step first; it 
**Original claims:** bug:gate-doc-refs-stale-verdicts

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
- 2026-11-20 06:35:55: conflicts with master (last commit 2026-11-20, first unlanded commit 2026-11-19; 2 commit(s) ahead of master, 67 behind it; task started 2026-11-20 01:40:41)
  Branch: work/fix-proof-bug-gate-doc-refs-stale-verdicts
  Conflicting files: bugs/hard/README.md
- 2026-11-20 (land worker): assessed; decision ADAPT, recorded in the landing commit.
  Branch now 2 ahead / 70 behind (merge-base 7400c7b85).
  - The branch's own test is the job `doc-refs-stale-verdicts` (`test_dangling_doc_refs.py`).
    It is GREEN on today's master (2026-11-20: 7/7 under memslot 8 GB), so it does not
    fail there: the bug the branch fixed is already fixed on master.
  - Master already carries the branch's fix, byte-identical: 8f7e64375 (2026-11-19
    21:21) deletes gate-doc-refs-stale-verdicts.md and makes the same README sync as
    the branch's 158cbe334 (same from/to blobs, 86a7095a2 -> 6d59fe17c) — parallel
    copies of one fix, and master kept its own. The branch's second commit 8d97fcf0e
    changes no file.
  - After 8f7e64375 the job went red again: at ef7029347^ the index held 11 rows to
    12 docs, the unindexed one being GATE_red_recover-land_2026-11-02-part5-part1.md
    (measured), and the integrator re-filed the doc (ef7029347). The part1 doc was
    closed and deleted in merge 76bfc1b8d (no row ever existed), and the c_common
    rows went with their docs (ae81bbf68, d960ce50f). The job has been green since
    (re-verified 2026-11-20: 9 docs = 9 rows; 7/7). The re-filed doc is now stale:
    job green, doc says red; its own rule is to delete it when the job is green.
  - The branch's README version is stale: it keeps the two rows for the closed
    c_common docs (COMPILE_FAIL_Tools_c-analyzer_c_common_{scriptutil,tables}.md,
    gone from bugs/hard on master); landing them would break the green
    HardIndexIsTrue check (a row naming a doc that is no longer in the tree).
    Master's README is strictly ahead of the branch's.
  - ADAPT: land the still-right part only — delete gate-doc-refs-stale-verdicts.md
    (the branch's 158cbe334 does exactly this) and pin it with a regression test in
    test_dangling_doc_refs.py; leave the README sync out (already on master since
    8f7e64375, and the branch's copy is behind it). Nothing more is owed to the
    branch; its tip is archived at
    refs/archive/work/fix-proof-bug-gate-doc-refs-stale-verdicts.
