# Land: should finished branch fix-proof-fix-gate-bootstrap-stage1-transitive land?

**Branch:** `work/fix-proof-fix-gate-bootstrap-stage1-transitive` (task `fix-proof-fix-gate-bootstrap-stage1-transitive`; its tip is also saved as `refs/archive/work/fix-proof-fix-gate-bootstrap-stage1-transitive`, so dropping it loses nothing).
**Age:** last commit 2026-11-18, first unlanded commit 2026-11-18; 3 commit(s) ahead of master, 85 behind it; task started 2026-11-18 09:56:34
**Original work:** Branch work/fix-gate-bootstrap-stage1-transitive (a finished worker branch; original task: The full gate (2557e196) is red on master in job `bootstrap-stage1-transitive`. Last working commit: 7b29b4f6
**Original claims:** gate:bootstrap-stage1-transitive

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
- 2026-11-18 20:20:29: worker says PARTIAL, not DONE, and no bug doc is left to continue it on (last commit 2026-11-18, first unlanded commit 2026-11-18; 3 commit(s) ahead of master, 85 behind it; task started 2026-11-18 09:56:34)
  Branch: work/fix-proof-fix-gate-bootstrap-stage1-transitive
- 2026-11-18: assessed on master/HEAD 7299a922a (`work/bug-land-bootstrap-stage1-transitive`).
  - Candidate refs: `work/fix-proof-fix-gate-bootstrap-stage1-transitive` = `refs/archive/work/fix-proof-fix-gate-bootstrap-stage1-transitive` = 15741ec50 ("review: bootstrap-stage1-transitive doc is stale; fix is on master and tested"), on top of 81d87e28f/ d52af8c66 from `work/fix-gate-bootstrap-stage1-transitive`.
  - Branch tip claims the underlying fix is on master (82884f350, integrated as 96cb967a4) and that `bugs/gate-bootstrap-stage1-transitive.md` was stale/re-filed; branch diff vs master is large and stale (`git diff --name-status master..refs/heads/work/fix-proof-fix-gate-bootstrap-stage1-transitive` shows many unrelated file changes), 85 commits behind per doc.
  - Master already contains `d682111e2 integrate fix-proof-bug-gate-bootstrap-stage1-transitive`; `bugs/gate-bootstrap-stage1-transitive.md` is absent on master.
  - Verified on master: `python3 tools/memslot.py --gb 8 --label t-container-param -- python3 test_codegen_container_param_unknown_arg.py` -> PASS (peak 0.2 GB, child exit 0). This is the existing regression test the branch cites as covering the fix.
  - Decision: **DROP**. Master already solves the problem and the branch is obsolete/stale (no part is still right to land against today's master). No original bug doc remains open for this issue. This commit series will delete this LAND doc and ratchet dangling refs.
