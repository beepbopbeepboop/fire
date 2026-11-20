SPLIT: GATE_red_recover-land_2026-11-02-part5-part2-part2 (part1 — the function-scoped sibling `STDLIB_PATH` weak stub — is fixed and its doc deleted; the imported-global accessor pass now covers function-scoped `from` imports and `module_loader.py` exports annotated scalar globals; the stage1 closure dump re-measure is the integrator's gate)

# Restore bootstrap stage2/stage3 dump jobs (replan part 2 of 5)

## Goal

With `bootstrap-stage1-transitive` green, make the bootstrap dump/compile chain that depends on it pass: `bootstrap-stage2-cc`, `bootstrap-stage2-dumps`, `bootstrap-stage2-transitive`, `bootstrap-stage3-dumps`, and `bootstrap-stage3-transitive`.

This is a follow-up replan part of `bugs/hard/GATE_red_recover-land_2026-11-02-part5.md` and depends on part 1 establishing a complete stage1 closure. The jobs must pass on their real outputs with the existing reject/expectations in `tools/suite.py` unchanged.

## Acceptance

- `python3 tools/suite.py bootstrap-stage2-dumps` and `python3 tools/suite.py bootstrap-stage3-dumps` each complete with a PASS verdict in `build/suite.log`, with their declared dependencies satisfied by the same run chain.
- No job is made green by an `expect=` marker, a skip, or a narrowed reject regex.

## Done when

File: `tools/suite.py` (registry entry for `bootstrap-stage3-dumps`; the job is the test)
Command: `python3 tools/suite.py bootstrap-stage3-dumps`
