# GATE: an OFF entry in `tools/gates.json` names a doc that no longer exists (23 jobs)

A landing-gate OFF entry must name the doc and the worker that own its backlog
(`tools/control.py:87`: "it must name the doc and the worker working the
backlog … so no gate is ever dropped silently"). One entry on this tree names
a doc that was deleted, so its backlog has no owner and can never be discharged
by the rule that removes it ("re-enable each one when fixed … and remove this
report in the same commit").

## What I ran / saw (2026-11-13)

    $ python3 tools/control.py gate list
    OFF  ^(async-void-return|bootstrap-stage1-transitive|coro|coro-detached-async|coro-future-await|doc-refs|doc-refs-stale-verdicts|formal-sweep-truth|formal-sys|gimple|gimplegenerators|gimplerunner|globcompiled|linkmode|modcache|mojoc|runtimediff|runtimedylib|runtimere|selfhost|silentnoop|sqliteruntime|suite-self-test)$ recover-land gate red (23 jobs); see GATE doc, re-enable each when fixed  (doc bugs/mid/GATE_red_recover_land_2026-11-02.md, worker integrator, since 2026-11-02 11:07:53)

    $ ls bugs/mid/GATE_red_recover_land_2026-11-02.md
    No such file or directory
    $ git log --oneline --diff-filter=D -- bugs/mid/GATE_red_recover_land_2026-11-02.md
    d44f44787 bugs: remove GATE_red_recover_land_2026-11-02 doc

The deletion commit's message says "Fixed root cause (coro.module_qualifier
missing as module attribute)" — one root cause, which cannot have covered all
23 jobs; the doc that owned the whole 23-job backlog was deleted instead of
being narrowed to what remained, and the OFF entry was left pointing at it. A
different branch's copy of the same cleanup (`770626a25`) blanked the `doc`
field instead; that version is not an ancestor of this tree, so HEAD still
carries the dead path.

The consequence is bigger than one job: `gimple`, `gimplerunner`, `linkmode`,
`selfhost`, `mojoc`, `coro`, `runtimediff` … are all skipped by every gate run
and there is nothing left in the tree that says why or who will look. The
`tests the gate actually runs` question is therefore answered by a 23-name
regex with no owner, and a worker cannot tell an intended backlog from a stale
entry.

## Expected

Every `off` entry names a `doc` that exists on disk and a `worker`, and the doc
says which jobs are still red and why. Fixing one job of a multi-job entry
narrows the entry; it does not delete the doc.

## Next step

1. Decide the live remainder: re-run each of the 23 jobs (or read
   `build/suite.log` from the last full run) and keep in the entry only those
   that are still red.
2. Re-file the remainder as one `bugs/<AREA>_<slug>.md` (or per-job docs if
   they are unrelated), and point the entry at it with
   `python3 tools/control.py gate off <pattern> --doc <path> --reason <why>`
   — or delete the entry with `python3 tools/control.py gate on <pattern>` when
   the remaining jobs are green.
3. Add the guard below so a deleted doc cannot leave a live OFF entry again.

## Done when

File: `test_gates_off_entries_name_a_doc.py` (repo root; created by this fix).

Command: `python3 test_gates_off_entries_name_a_doc.py`

It loads `tools/gates.json` and asserts, for every `off` entry: `doc` is a
non-empty path, `os.path.exists(doc)` is true, and `worker` is non-empty.
Red today: the 23-job entry's `doc` is
`bugs/mid/GATE_red_recover_land_2026-11-02.md`, which does not exist.
