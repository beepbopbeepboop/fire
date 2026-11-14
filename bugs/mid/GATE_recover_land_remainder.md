# GATE: recover-land backlog remainder (23 jobs) — OFF entry owner doc

## Status (2026-11-13, OPEN; remainder untriaged on current HEAD)

The OFF entry in `tools/gates.json` matching

    ^(async-void-return|bootstrap-stage1-transitive|coro|coro-detached-async|coro-future-await|doc-refs|doc-refs-stale-verdicts|formal-sweep-truth|formal-sys|gimplegenerators|gimplerunner|globcompiled|linkmode|modcache|mojoc|runtimediff|runtimedylib|runtimere|selfhost|silentnoop|sqliteruntime|suite-self-test)$

previously named the deleted `bugs/mid/GATE_red_recover_land_2026-11-02` doc, which was removed
in `d44f44787` ("Fixed root cause (coro.module_qualifier missing as module
attribute)") while the OFF entry was left pointing at the deleted path. That
left 23 gated jobs skipped with no owning doc.

This doc re-establishes the owner for that OFF entry. The live remainder has
**not** been fully re-triaged on this HEAD: `build/suite.log` is not present in
this worktree and re-running all 23 jobs (including compiled-path/bootstrap
coverage such as `selfhost`, `mojoc`, `linkmode`, `bootstrap-stage1-transitive`)
is outside a light worker's budget. Treat every job in the pattern as still part
of the backlog until individually verified green and removed from the entry.

## Original context (carried over from the deleted `GATE_red_recover_land_2026-11-02` doc)

The `recover-land` round (branch `work/recover-land`, base `8b69d5a8b`) gated RED
on 2026-11-02 with 23 jobs failing. Known observations from that report:

- `gimple` had 4 pre-existing failures on master at the time of that report.
- `coro` failed on master without recovery commits; `doc-refs` passed on rerun
  but failed in the gate (cause unexplained in that report).
- Repeated error seen: `module 'mojo.middle.coro' has no attribute 'module_qualifier'`.
- `bootstrap-verify` / `bootstrap-validate` were reported as still running while
  these 23 were OFF.

## Next step

1. Re-run each job in the pattern (or consult a fresh full gate log) on current
   master/HEAD and narrow the OFF entry to jobs that are still red.
2. For each job proven green, remove it from the regex (or `gate on` when empty)
   in the same commit as the evidence.
3. Split unrelated failures into separate bug docs with their own OFF entries if
   needed, keeping every OFF entry's `doc` pointing at an existing file.

## Done when

`python3 tools/memslot.py --gb 8 --label gate-off-doc -- python3 -m unittest test_gates_off_entries_name_a_doc.py -v`
passes, proving every `tools/gates.json` OFF entry names an existing doc and
worker (so the 23-job recover-land entry is owned by a live doc, not a deleted
path).