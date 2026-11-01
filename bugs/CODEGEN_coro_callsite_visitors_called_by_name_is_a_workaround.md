# CODEGEN: `mojo/middle/coro.py` calls the callsite visitors by name — a workaround that the root fix made redundant

## Status (2026-11-01)

Commit `0f009480b` worked around a NULL-environment crash in the self-hosted
compiler by calling `coro`'s callsite visitors by name instead of passing them
on as values from inside another nested function. Master then fixed the
underlying bug at its root in `145fd1089` (a capturing nested function used as
a value inside another nested function now gets its env). Both fixes are now in
the same tree.

The workaround is therefore redundant, and it is the "two fixes for one thing"
shape CLAUDE.md asks us to consolidate. It was NOT reverted here because
restoring the value-passing form changes the self-hosted compiler's own code,
and the proof it is safe is the self-host build (`test_selfhost.py`'s
`CALL_PROGRAM` probe, plus `make bootstrap`), which a light worker may not run.

## Status (2026-11-01, worker landing)

Step 1 LANDED on master as `86746ec60` (the earlier branch name cited here,
`...-5724`, no longer exists; the commit is the authoritative record): the
by-name calls in `mojo/middle/coro.py` `_scan_callsite_param_kinds` are reverted
to passing `visit` as a value (`_collect_from(src, visit, closure)`,
`_visit_call(node, caller_env, callee=None)`), and the workaround comment is
removed. `test_coro_bugs.py` passes (exit 0, re-run 2026-11-01 under
`memslot --gb 8`, peak 0.1 GB).

No light regression test is possible for this shape: the failure exists only
in the self-hosted binary's NULL-env codegen, which no python-interpreted test
reaches. The only coverage is the `CALL_PROGRAM` probe in `test_selfhost.py`
and `make bootstrap`, both heavy.

NOT verified here: steps 2-3 (`test_selfhost.py` `CALL_PROGRAM` probe and
`make bootstrap`) are heavy self-host runs, reserved for the integrator. This
doc is NOT deleted until they pass. If the probe fails, step 4 applies: restore
the by-name form and record the failing shape here.

## Next step

1. Revert the by-name calls in `mojo/middle/coro.py` (the comment block near
   line ~5012 that describes the by-name calls) back to passing the visitors as
   values, keeping the behaviour identical.
2. Run `python3 test_selfhost.py` (the `CALL_PROGRAM` probe must still compile
   and run) — heavy, integrator's job.
3. Run `make bootstrap` — the three stage trees must stay byte-identical.
4. If the probe fails after the revert, the root fix from `145fd1089` does not
   cover this shape; re-add the workaround and record the failing shape here
   instead.

Delete this doc in the same commit as step 1 if steps 2-3 pass.
