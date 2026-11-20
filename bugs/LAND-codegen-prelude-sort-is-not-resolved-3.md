# Land: should finished branch bug-codegen-prelude-sort-is-not-resolved-3 land?

**Branch:** `work/bug-codegen-prelude-sort-is-not-resolved-3` (task `bug-codegen-prelude-sort-is-not-resolved-3`; its tip is also saved as `refs/archive/work/bug-codegen-prelude-sort-is-not-resolved-3`, so dropping it loses nothing).
**Age:** last commit 2026-11-19, first unlanded commit 2026-11-19; 4 commit(s) ahead of master, 109 behind it; task started 2026-11-19 22:15:27
**Original work:** An earlier attempt left 3 commit(s) on branch work/bug-codegen-prelude-sort-is-not-resolved, which you start from. Read `git log master..HEAD` and `git diff master...HEAD` first. Fix the bug in bugs/C
**Original claims:** bug:CODEGEN_prelude_sort_is_not_resolved

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
- 2026-11-20 05:38:29: conflicts with master (last commit 2026-11-19, first unlanded commit 2026-11-19; 4 commit(s) ahead of master, 109 behind it; task started 2026-11-19 22:15:27)
  Branch: work/bug-codegen-prelude-sort-is-not-resolved-3
  Conflicting files: bugs/CODEGEN_prelude_sort_is_not_resolved.md, mojo/backend_gimple/module_gen.py
