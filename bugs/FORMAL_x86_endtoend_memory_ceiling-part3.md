# FORMAL_x86_endtoend_memory_ceiling-part3: Set the three memory-ceiling proofs' `-M` from the measured record

## Goal

Fill `PROOF_MEMORY_MB` (part1's table in `formal/lean.py`) for `wide_expr`, `wide_recv`, and `list_literal_index` with a ceiling derived from the peak RSS recorded in `formal/proof_memory_peaks.json` (part2), so each of the three gets the memory it measurably needs and no more. Nothing else's ceiling changes.

The rule for the value: `ceiling_mb = ceil_to_512(peak_rss_mb * 1.25)`, with a floor of the default `LEAN_MEMORY_MB` (6144). The 1.25 margin and the 512 MB rounding are the only numbers this part chooses; record them as named constants next to the table, not inline.

If any stem's measured peak needs more than 8192 MB, do NOT raise its entry above 8192. Leave that stem out of the table, and file the remainder as a bug doc (see Done when, last clause).

## Acceptance

- `formal/lean.py`'s `PROOF_MEMORY_MB` has entries for exactly the stems whose measured peak fits under 8192, each equal to the rule's value for its recorded peak.
- No other proof's `-M` changes: `proof_memory_mb` for every other stem still returns 6144.
- The three stems' ceilings are read by `check_proof_cached` through part1's resolver, so the argv Lean receives is the table value.

## Done when

`python3 test_formal_lean_proof_memory_ceiling.py TestMemoryCeilingTableMatchesRecord`

Add class `TestMemoryCeilingTableMatchesRecord` to `test_formal_lean_proof_memory_ceiling.py` (created by part1), which:
- (a) loads `formal/proof_memory_peaks.json`; if the file is absent the test FAILS with a message naming part2 (it must not skip, since a skip would hide the missing measurement);
- (b) for each stem in the record, asserts `PROOF_MEMORY_MB[stem] == ceil_to_512(peak_rss_mb * 1.25)` when the peak fits under 8192, and that the stem is absent from the table otherwise;
- (c) asserts `proof_memory_mb` returns the table value for each stem in the table and 6144 for a stem that is not.

Run it alone; it touches no Lean.

If a measured peak exceeds 8192 MB, this part is NOT done: it must still land the entries it can, and file a new bug doc under `bugs/` titled for the over-8 GB case (the memory-ceiling proof that still exceeds an 8192 MB `-M`), naming the stem, its measured peak, and the exact next step (the `hval` chain cost reduction in the original bug's step 2). That new doc is the owner of the remaining work.

## Notes

- Depends on part1 (the table and resolver) and part2 (the record). Do not start until both are on master.
- This part changes a bound, so per the bug-doc rules it must say in the commit message which numbers were chosen and from which record date.
- The original doc's "Done when" also requires that no generated proof in the corpus is rejected by `-M`. That is a whole-corpus run for the integrator (`formal-x86-endtoend` job), not this part's test. Record in the report that it still needs to run.
- Do not raise `LEAN_MEMORY_MB` itself. The default stays 6144 for every other proof; that is the policy the original bug calls out as not something the environment can lift.
