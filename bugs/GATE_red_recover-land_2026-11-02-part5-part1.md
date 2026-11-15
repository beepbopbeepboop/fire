# Restore bootstrap-stage1-transitive closure completeness (replan part 1 of 5)

## Goal

Make `bootstrap-stage1-transitive` pass by ensuring the Python `--dump-full` closure of `fire.py` contains no `unavailable in compiled mode` stubs and no `# ERROR: compiling imported module`, so the job's `CLOSURE_INCOMPLETE` reject no longer fires.

This is a follow-up replan part of `bugs/hard/GATE_red_recover-land_2026-11-02-part5.md`. Parts 1–4 of the parent `GATE_red_recover-land_2026-11-02` chain are already landed on master; if the closure dump still names a weak stub that those parts do not explain, fix it here only if it is a one-symbol registration of the same shape those parts already handle. Otherwise file it as a new `bugs/` doc with a minimal probe and leave this part open rather than masking the stub.

## Acceptance

- `python3 tools/suite.py bootstrap-stage1-transitive` completes with a PASS verdict in `build/suite.log`.
- The run is not made green by an `expect=` marker, a skip, or a narrowed reject regex in `tools/suite.py`.
- The produced closure dump for `fire.py` has no `unavailable in compiled mode` and no `# ERROR: compiling imported module`.

## Done when

File: `tools/suite.py` (registry entry for `bootstrap-stage1-transitive`; the job is the test)
Command: `python3 tools/suite.py bootstrap-stage1-transitive`
