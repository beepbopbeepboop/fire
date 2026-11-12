# CODEGEN_tagged_generator_mixed_type_step4-part1: container census — record the representation decision

**Parent BUG:** `bugs/hard/CODEGEN_tagged_generator_mixed_type_step4.md` (plan step 4, "remove the refusal"; floats and strs are done).
**Class:** easy (this doc lives in `bugs/`).

## Goal

Close the one open question blocking the container case of step 4: does any
real `.mojo` source bind one name BOTH to a container value and to a tagged
generator word (`x = [1, 2]` … `for v in g(): x = v`)? Record the measured
answer as a decision (option 1: a container-kind box; option 2: keep the
refusal as a diagnostic that names the two bindings) in the docs that carry
it. No compiler code changes — that is part2.

## Current state (measured 2026-11-12, on this branch's HEAD)

- `bugs/mid/CODEGEN_tagged_generator_mixed_type_container.md` holds the open
  decision and says exactly what measurement settles it: grep the stdlib and
  `test/` corpus for the rebind shape; if none, option 2 closes the doc.
- The reproducible census probe is committed as `test_tagged_container_corpus.py`
  (repo root). Its 2026-11-12 run:

      census: stdlib: 610 .mojo files scanned
      census: repo: 226 .mojo files scanned
      census: candidates (...): 0
      census: parse failures: 0

  (610 files under `$MOJO_STDLIB`/the `module_loader` preferred checkout,
  226 under the repo root, every file containing `yield` parsed cleanly.)
- The remaining refusal for the container case lives at the simple-name arm
  of `mojo/backend_gimple/emit_stmts.py` (the `is_non_int_c_type(vtype)` half,
  true for any pointer type other than the already-boxed `char *`), shared
  text `MIXED_NAME_NON_INT64_REFUSAL` in `mojo/backend_gimple/emit_infra.py`.

## Scope

1. Re-run the probe and confirm the counts (step 2 of the container doc):

       python3 tools/memslot.py --gb 8 --label tagged-container-census -- python3 test_tagged_container_corpus.py

2. If the candidate count is 0, record the decision in
   `bugs/mid/CODEGEN_tagged_generator_mixed_type_container.md`'s Status:
   option 2, the date, the counts (stdlib/repo files scanned, candidates 0),
   and the exact probe command. If the candidate count is non-zero, review
   each printed candidate by hand; a real kind-mixed generator rebinding a
   container to its loop variable flips the decision to option 1 — **STOP and
   report NEEDS-INFO** with the candidates listed (part2's scope was set by
   the option-2 outcome; it must not be silently retargeted).
3. Amend `docs/tagged_generator_mixed_type-plan.md`'s step 4 to state the
   decision in one paragraph: floats and strs are done; containers are
   refused by design; the refusal now names the two bindings (that diagnostic
   is part2's work). Keep the plan's step numbering and the rest of the doc
   untouched.
4. Do not change compiler code, runtime code, or tests other than the probe.

## Acceptance

- `bugs/mid/CODEGEN_tagged_generator_mixed_type_container.md` records option 2
  with the measured counts and the probe command (or the NEEDS-INFO stop path
  with the candidates listed).
- `docs/tagged_generator_mixed_type-plan.md` step 4 reflects the decision.
- `python3 test_tagged_container_corpus.py` exits 0.

## Done when

File: `test_tagged_container_corpus.py` (repo root).

Command:

    python3 test_tagged_container_corpus.py

It exits 0, prints both per-corpus scan counts, the candidate count, and the
parse-failure count; the decision recorded in the docs must quote exactly
those numbers. It exits 3 (not 0) when no stdlib root is reachable, so it
cannot pass by scanning nothing.

## Not in this part

The diagnostic itself, the tests for it, and the deletion/update of the
container doc — part2
(`bugs/mid/CODEGEN_tagged_generator_mixed_type_step4-part2.md`).
