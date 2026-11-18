# Land: should finished branch bug-gate-stdlib-syntax-3 land?

**Branch:** `work/bug-gate-stdlib-syntax-3` (task `bug-gate-stdlib-syntax-3`; its tip is also saved as `refs/archive/work/bug-gate-stdlib-syntax-3`, so dropping it loses nothing).
**Age:** last commit 2026-11-18, first unlanded commit 2026-11-15; 4 commit(s) ahead of master, 864 behind it; task started 2026-11-18 01:49:17
**Original work:** An earlier attempt left 2 commit(s) on branch work/bug-gate-stdlib-syntax-2, which you start from. Read `git log master..HEAD` and `git diff master...HEAD` first. That branch deleted the doc, which is
**Original claims:** bug:gate-stdlib-syntax

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
- 2026-11-18 02:57:56: conflicts with master (last commit 2026-11-18, first unlanded commit 2026-11-15; 4 commit(s) ahead of master, 864 behind it; task started 2026-11-18 01:49:17)
  Branch: work/bug-gate-stdlib-syntax-3
  Conflicting files: see `git merge master`
