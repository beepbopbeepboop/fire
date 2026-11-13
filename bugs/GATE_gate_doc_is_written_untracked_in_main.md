# GATE: a red-gate doc is written untracked in MAIN, so no worker sees it and no ledger commit can land

**Job:** `stdlib-syntax`; the gate doc that was fed to task
`bug-gate-stdlib-syntax` (deleted on 2026-11-13 — it was the generic six-line
template, not a live measurement).

## Symptom

Two failures with one cause, measured 2026-11-13.

1. **The worker spawned for the doc does not have it.** Task
   `bug-gate-stdlib-syntax` starts with the instruction to fix the gate doc for
   `stdlib-syntax`, but its worktree is cut from `master`, where the doc is not
   tracked: `git status --short` in the new worktree is empty and the file does
   not exist. The only copy was untracked in the main checkout
   (`/Users/mrs/net/chatgpt/claude/mojo-reference`, `?? gate-stdlib-syntax.md`
   — deleted since).
   A worker may not edit MAIN, so it cannot delete the doc either; the claim
   (`bug:gate-stdlib-syntax`) keeps being fed even after the job goes green.

2. **The untracked twin blocks every `verify-ledger` landing.** The ledger
   commit carries the `disabled=` markers and docs for *all* red jobs, and git
   refuses to merge it while MAIN has an untracked file at the same path:

       ledger commit 0659a5c202 NOT landed (failed: error: The following
       untracked working tree files would be overwritten by merge:
           gate-stdlib-syntax.md               # the orphan, deleted since
       Please move or remove them before you merge.
       Aborti); it stays on branch verify-ledger
       full gate RED: formal-doc-truth, rthdrscan, stdlib-syntax, 380s

   That line repeats for `02080b3033`, `b22d219e94`, `99c17d785f`, `5c0603122a`
   and `5799bcde36` in `.git/control/verify.out`, so one orphan doc held up the
   ledger for every other job too. The last date it recurred is 2026-11-13
   06:16 (`verify-de544e7d.log`).

The job was already green when this was filed: `work-verify/build/suite.log`
has `[116/152] ok stdlib-syntax 11.7s` at `11dffba0e`, and the integrator's
landing run at `e9f5b5403` has `[1/1] ok stdlib-syntax 77.2s`. The doc's own
content was the generic gate template (six lines, no `## Status` and no
`## Done when`), i.e. a stale artifact, not a live measurement.

## Cause

`tools/integrate.py::gate_doc` writes `bugs/gate-<job>.md` with

    p = os.path.join(C.MAIN, "bugs", "gate-%s.md" % j)
    ...
    open(p, "w").write(...)

and never commits it. `tools/verify_landed.py` writes *its* doc into
`work-verify/bugs/`, commits it on `verify-ledger`, and lands that commit on
master. The two writers race: the tracked version in the ledger commit cannot
be merged because the untracked `gate_doc` twin is in the way, and nothing
removes that twin. `verify_landed.apply_findings`'s recovery path only removes
the doc in `VERIFY` (`git rm -q -f` relative to `VERIFY`), never MAIN's.

## Reproduce

At the time of filing:

    git -C /Users/mrs/net/chatgpt/claude/mojo-reference status --short
    # ?? gate-stdlib-syntax.md               (deleted since)
    grep -n "would be overwritten" /Users/mrs/net/chatgpt/claude/mojo-reference/.git/control/verify.out

and confirm the job is not red (both logs above say `ok stdlib-syntax`).

## Next step

Make the doc a tracked thing from the moment it is created, and make the
ledger landing robust to a leftover twin:

- **`integrate.py::gate_doc`**: create the doc where it will be committed, and
  land it on master in the same step that any other master-touching decision is
  landed (the integrator lock path `verify_landed.land_ledger` already does
  this for its own docs). A `gate_doc` that simply leaves the file in MAIN's
  working tree is the bug: the feeder enqueues work from `doc_exists_for`
  (a filesystem walk), while the worker is cut from a git commit, so the two
  disagree about whether the doc exists.
- **`verify_landed.land_ledger`**: before `SF.merge`, remove a MAIN-untracked
  `bugs/gate-*.md` that the ledger commit tracks
  (`git ls-tree -r --name-only verify-ledger -- bugs/gate-*.md` intersected with
  `git -C MAIN ls-files --others --exclude-standard`). The tracked version in
  the commit supersedes the orphan, so deleting the twin is safe and is the
  difference between "the ledger lands" and "every job's marker stays on the
  branch".
- **Test**: extend `tools/test_gate_doc.py` so `gate_doc()` must hand back a
  path that is *tracked on the branch the task starts from* (a worktree cut
  from that branch sees it), and so `apply_findings`/`land_ledger` lands onto a
  MAIN that has the same doc untracked. Both fail on the code as filed.

The orphan copy this doc is about was removed by hand (it had no other
content), so the immediate merge blocker is gone; the code defect above is not.
