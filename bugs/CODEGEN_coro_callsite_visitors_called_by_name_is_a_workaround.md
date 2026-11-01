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
