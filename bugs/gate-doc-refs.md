# Gate: doc-refs is red on master

**Job:** `doc-refs`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py doc-refs`), then fix the cause. Do not skip or mark the test.

## Status 2026-11-15: filed from the gate-defaulted-trait-method-conformance-diagnostic lane

Noted while deleting the defaulted-trait-method-conformance gate doc
(no file cited it, so that deletion added no dangling citations).
`python3 tools/dangling_doc_refs.py --ratchet` fails identically at
master's tip (6b7ed9014) and on this branch: exactly ONE file is over its
baseline, `bugs/LAND-codegen-nested-bracket-generic-call-4.md` (count 5,
baseline 0), and every one of its five citations points at a doc that is
gone. Run `python3 tools/dangling_doc_refs.py` (no `--ratchet`) to list
the five names; they are the Status-log line in that doc recording the
uncommitted entries of worktree work-7059 — five doc paths logged verbatim,
all since deleted with their fixes.

`bugs/LAND-codegen-nested-bracket-generic-call-4.md` is byte-identical to
its master copy, so the red predates any branch off 6b7ed9014. It appeared
AFTER the 2026-11-15 10:13 gate round — the LAND doc landed at d4e7a742e
(10:31) — which is why no gate doc for this job existed when this lane ran.

Next step: the `bug:LAND-codegen-nested-bracket-generic-call-4` lane already
instructs its resolver to `git rm` that doc and run the ratchet in its
closing commit; that removes all five citations and this job goes green.
If the doc instead survives (LAND/ADAPT outcome), rewrite the five
historical citations to name the bugs (their symptoms or fixing commits)
so the count drops to the baseline of 0, or raise the ceiling in
`tools/dangling_refs_baseline.py` on purpose with a comment.
