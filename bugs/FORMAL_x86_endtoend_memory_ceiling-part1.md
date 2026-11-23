# FORMAL_x86_endtoend_memory_ceiling-part1: Per-proof `-M` ceiling, keyed by proof file

## Goal

Every generated proof is checked under one number: `formal/lean.py`'s `LEAN_MEMORY_MB = 6144`, applied in `lean_flags` (line ~315) and used as the default by `proof_verdict_key` and the `mem_mb=None` paths of `proof_census` / `check_proof_cached` / `check_proof`. The three memory-ceiling proofs (`wide_expr`, `wide_recv`, `list_literal_index`) need a different bound, and the only way to give them one today is to raise it for everything.

Add ONE table, `PROOF_MEMORY_MB` in `formal/lean.py`, mapping a proof's example stem (the `<stem>` of `<stem>.lean` / the generated proof file) to an `-M` value in MB, plus ONE resolver, `proof_memory_mb(proof_path) -> int`, that returns the table entry or `LEAN_MEMORY_MB`. Route every `mem_mb is None` default through the resolver so the table is consulted at each call site that today reads `LEAN_MEMORY_MB` directly (`lean_flags` callers, `proof_verdict_key`). Do NOT change any table value in this part: the table starts with no entries for the three stems, so behaviour is unchanged until part3 fills them in.

This part is mechanism only. It must not raise any ceiling and must not run Lean.

## Acceptance

- `formal/lean.py` has exactly one place that maps a proof file to its `-M`: `proof_memory_mb`. `grep -n "LEAN_MEMORY_MB" formal/lean.py` shows the constant, the table default, and the resolver; no other read of the constant on a proof path.
- For a proof path whose stem is not in `PROOF_MEMORY_MB`, the resolved value is `LEAN_MEMORY_MB` (6144): behaviour is unchanged for the whole corpus.
- For a stem that IS in the table, `check_proof_cached` / `proof_census` pass that value as `-M` to `lean` (observable in the argv `run_lean` receives), and the verdict key changes with it (the `proof_verdict_key` already folds `mem_mb` in, so a raised value cannot replay a verdict recorded under the old ceiling).
- A caller that passes an explicit `mem_mb` still wins over the table.

## Done when

`python3 test_formal_lean_proof_memory_ceiling.py TestPerProofMemoryCeiling`

Create `test_formal_lean_proof_memory_ceiling.py` with class `TestPerProofMemoryCeiling`, which:
- (a) monkeypatches `formal.lean.run_lean` (or the lowest subprocess seam it uses) to record argv and return a canned successful result, so NO Lean process is started;
- (b) for a stem present in a test-local table patched into `PROOF_MEMORY_MB` (e.g. `"wide_expr": 8192`), asserts the recorded argv contains `-M 8192`;
- (c) for an absent stem, asserts `-M 6144`;
- (d) asserts an explicit `mem_mb=4096` argument overrides the table;
- (e) asserts `proof_verdict_key` differs between 6144 and 8192 for the same proof bytes.

The test must not invoke `lean`, must not touch `lib/`, and must run in well under a second.

## Notes

- Touches only `formal/lean.py` and the new test file. `formal/x86_64_endtoend_test.py` needs no change: it reaches `lean` through the same `check_proof_cached` path.
- Do not change `LIBRARY_MEMORY_MB` or the library build path; that ceiling is a separate policy.
- The existing `test_formal_x86_64_endtoend_memory_ceiling.py` (already on master, passing) covers the simp-set fix and must keep passing; it does not exercise `-M`.
- Parts 2 and 3 of this bug depend on this mechanism: part2 measures peaks by passing an explicit `mem_mb`, part3 fills the table.
