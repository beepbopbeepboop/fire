# ORCHESTRATION_kills_log_refused_flood

## Summary
`.git/control/kills.log` gets one `REFUSED` line per pass for the same task and process group, so the file grew to
1.3 MB in about an hour (4,612 REFUSED lines). The noise hides real kill events.

## Evidence
- Lines repeat for the same pgid, e.g. `REFUSED task=bug-formal-formal-function-value-calls-a-6227 pgid=2769` on
  consecutive passes, with the leader already gone.
- The refusals are the safe behaviour. The problem is that they are logged every pass with no dedupe.

## Repro
Leave a task whose process group leader has exited. Count `REFUSED` lines over a few passes.

## Status
Open. Not started. Log a refusal once per (task, pgid) until its state changes.

## Done when
A refused kill is logged once per (task, pgid, reason) and `kills.log` stops growing while nothing changes,
with a test. Then delete this doc in the same commit.
