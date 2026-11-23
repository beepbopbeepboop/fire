# FORMAL_x86_endtoend_memory_ceiling-part2: Measure each memory-ceiling proof's peak RSS under a raised `-M`

## Goal

The original bug's first next step is to measure, not guess: how much memory each of the three memory-ceiling proofs actually needs. The measurement cannot be taken under the current 6144 MB ceiling (that is the failure), so it must run with a raised ceiling and record the peak. Land the measurement HARNESS and the RECORD SCHEMA as code, with a cheap test. The heavy Lean runs themselves are the integrator's to execute; this part's worker does not run them.

Add `tools/measure_proof_peaks.py`. For each stem in `wide_expr`, `wide_recv`, `list_literal_index` it:
- generates the proof (the same path `formal/x86_64_endtoend_test.py` uses for that example);
- runs `lean` on it with an explicit `mem_mb=8192` (through `formal.lean`'s existing `mem_mb` parameter, not by editing `LEAN_MEMORY_MB`), wrapped in `python3 tools/memslot.py --gb 8 --label measure-<stem> -- ...` or the equivalent so it reserves memory and is killed at 8 GB;
- records `{stem, returncode, peak_rss_mb, wall_s, lean_version, mem_limit_mb: 8192, ran_at}` into `formal/proof_memory_peaks.json` (a JSON object keyed by stem).

The harness must support `--dry-run` that prints the argv it would run for each stem without starting Lean. The dry run is the part's test surface.

## Acceptance

- `python3 tools/measure_proof_peaks.py --dry-run` prints, for each of the three stems, the `lean` argv including `-M 8192`, and the memslot wrapper, and exits 0; it starts no process.
- The JSON record written by a non-dry run has one entry per stem with all six fields, and the peak is read from the process's own peak RSS (`resource.getrusage(RUSAGE_CHILDREN)` per child, or the memslot log), not estimated.
- A stem whose run is killed by the ceiling or refused by Lean (`excessive memory consumption`, rc -6 or 1) is recorded with its real returncode and `peak_rss_mb` as reached, not dropped and not marked passing.

## Done when

`python3 test_measure_proof_peaks.py TestMeasureProofPeaksSchema`

Create `test_measure_proof_peaks.py` with class `TestMeasureProofPeaksSchema`, which:
- (a) imports the harness and asserts its stem list is exactly `wide_expr`, `wide_recv`, `list_literal_index`;
- (b) runs `--dry-run` as a subprocess and asserts each stem's argv contains `-M 8192` and that no `lean` process is spawned (assert via a patched `subprocess.Popen` in-process, or by checking the harness exposes its argv builder and calling that);
- (c) validates a hand-written fixture record (a temp file under `.tmp/`, not the real JSON) against the schema: six fields present, `peak_rss_mb` a non-negative int, `mem_limit_mb == 8192`.

The test must not run Lean and must finish in under a few seconds.

## Notes

- Depends on part1 for `mem_mb` routing being clean, but only uses the explicit `mem_mb` parameter, so it can be built before part1 lands if needed.
- The integrator, not this part's worker, runs the non-dry measurement and commits `formal/proof_memory_peaks.json`. This part's done-when does not require that file to exist.
- Part3 reads `formal/proof_memory_peaks.json`. If the record is missing when part3 runs, part3 is blocked, not failed.
- Record the measurement date and the `lean` version in the JSON so a later run can tell whether the numbers are stale.
- Original doc's 2026-11-19 figure (`list_literal_index` peaked at 6.6 GB) predates the hmem simp-set fix (`21a94df97`, `6166fa64e`) on master. Expect lower numbers; do not assume them.
