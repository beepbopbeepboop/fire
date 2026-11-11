# ORCHESTRATION_hard_class_no_slot

## Summary
Docs in `bugs/hard/` (class `hard`, Opus) have no slot to run in, because `tools/pool.json` sets the `opus` slot
to `count: 0`. Those docs wait forever, and the swarm logs the fact on every pass with no owner decision attached.

## Evidence
- Swarm log: `config: class(es) with docs but no slot: hard (opus count 0)` on every pass.
- Five hard docs were ready to run and none started (`refill: 0 running ... 36 still queued`).

## Repro
`python3 tools/control.py refill` with `bugs/hard/*.md` present and `opus` at count 0: nothing starts for `hard`.

## Status
Open. Not started. Needs an owner decision: set the opus count, or move hard docs to a class that runs.

## Done when
The owner has decided the `hard` slot policy, and `pool.json` matches it, with the swarm no longer logging the
warning for an accepted policy. Then delete this doc in the same commit.
