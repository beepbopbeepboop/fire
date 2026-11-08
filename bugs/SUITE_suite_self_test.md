# SUITE_suite-self-test: make check failure

**Status:** PARTIAL — investigated 2026-11-07 on `work/bug-suite-suite-self-test`.

Job `suite-self-test` runs `python3 test_suite.py` (`tools/suite.py`). It failed
with an unhandled `FileNotFoundError` in
`test_formal_sweep_work_map_index_tags_only_from_section3`
(`test_suite.py`), which opened `bugs/FORMAL_sweep_work_map.md`
unconditionally even when that consolidated file was missing. The exception
aborted the whole self-test (exit 1) before reporting its checks.

**Landed:** `test_formal_sweep_work_map_index_tags_only_from_section3` now
guards the missing file and records a named `check()` failure instead of
crashing, so `suite-self-test` completes and reports all failures.

**Verified:** `python3 tools/memslot.py --gb 8 --label suite-self-test --
python3 test_suite.py` completes (no traceback) and reports `361 passed, 15
failed` (exit 1). The previous run crashed mid-file at the missing sweep-map
open.

**Still failing inside `test_suite.py` (blocks a green `suite-self-test`), many
in other workers' claimed areas:**
- dangling refs (`SUITE_doc_refs` / `SUITE_doc_refs_stale_verdicts`)
- formal doc index (`SUITE_formal_doc_truth`)
- sweep maps consolidated-file / index pins (`SUITE_formal_sweep_truth` domain;
  consolidated `bugs/FORMAL_sweep_work_map.md` missing)
- stale verdicts ledger (`SUITE_doc_refs_stale_verdicts`)
- estate: 26 undeclared `test_*.py` files
- buckets: `formal-eh-tables`, `formal-once-bound-strings`,
  `formal-str-trim-runtime`, `formal-try-model` registered but in no bucket
- budgets residue census drift
- self-host key missing hashed `formal/*` modules
- `formal-proof-gaps` missing `memwhy` pointing at
  `doc/POLICY_memory_over_4gb.md`
- `expect` reasons cite missing docs:
  `bugs/hard/CODEGEN_ab_native_fails.md` (`ab-native`, claimed by
  `fix-gate-ab-native`) and
  `bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`

**Next step:** resolve the remaining failures by area/claim (or re-triage
`suite-self-test` once those bugs land), then confirm
`python3 tools/memslot.py --gb 8 --label suite-self-test -- python3
test_suite.py` exits 0.
