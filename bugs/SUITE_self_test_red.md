# SUITE `suite-self-test` is red on master (estate, residue census, doc refs)

**Job:** `suite-self-test`. Found by the merge lane
`fix-merge-bug-mid-diagnostics-trait-conformance-pa-3` while verifying that
branch. Nothing this branch touched is among the rows: the files below landed
on master from other lanes, and a pristine `master` snapshot run reproduces
the same rows (the snapshot additionally reports the glob/walk row, which is
an artifact of running from an extracted archive with no `.git`).

Reproduce:

    python3 tools/memslot.py --gb 8 --label suite-selftest -- python3 test_suite.py

Result on master (`b521a1729`, re-checked after `56066b33a`) and on top of
this branch: `372 passed, 5 failed` (the branch adds one passing pin and one
passing suite row, so the count is 2 higher than master's own run).

## Failing rows

1. **budgets: the residue census is the residue.**
   `test_interp_list_ctor.py`: census 0 vs walk 1;
   `test_module_globals_compiled.py`: census 0 vs walk 3;
   `test_regress_gpu_offload_validation_modular_part4.py`: census 0 vs walk 1.
   The three test files carry a memory literal (`--gb`/`mem=` value) but no
   `MEM` census row in `test_suite.py`.

2. **budgets: the residue is not allowed to GROW.**
   `39 files carry a literal against a census of 36` — the same three files as
   row 1, seen by the ratchet.

3. **the estate: every test file is run by something.**
   `test_interp_list_ctor.py` and `test_module_globals_compiled.py` are named
   by no registered spec, are not in `UNREGISTERED`, and belong to no declared
   family. (`test_regress_gpu_offload_validation_modular_part4.py` is
   registered; only its census row is missing.)

4. **dangling refs: the corpus outside `test_suite.py` is empty.**
   9 citations of deleted `bugs/mid/...` paths remain in docs that master's
   `bugs/` reorganisation moved to `bugs/` root without updating the citations:

   | cited (absent) | citing file |
   |---|---|
   | `mid/COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part3.md` | `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` |
   | `...-part4.md` | same |
   | `...-part5.md` | same |
   | `mid/DIAGNOSTICS_mojoc_imports-part1.md` | `bugs/hard/DIAGNOSTICS_mojoc_imports.md` |
   | `mid/DIAGNOSTICS_mojoc_imports-part3.md` | same |
   | `mid/DIAGNOSTICS_mojoc_imports-part2-part1.md` | `bugs/hard/DIAGNOSTICS_mojoc_imports-part2.md` |
   | `...-part2-part2.md` | same |
   | `...-part2-part3.md` | same |
   | `mid/GPU_offload_validation_modular-part1.md` | `bugs/GPU_offload_validation_modular-part2.md`, `...-part3.md` |

5. **dangling refs: the BARE class ledger.**
   `BARE_BASELINE has 47 entries and the corpus has 46 citing files; gains
   [('tools/control.py', 4, 2)]` — `tools/control.py` grew two bare citations
   (the report and task-report names it uses) after the baseline was written.
   `python3 tools/dangling_doc_refs.py --ratchet` additionally reports 8 files
   over their prefixed ceilings (the same 10 names above, plus
   `tools/test_swarm_replan.py: 2 (baseline 1)` for `hard/Xcase.md`) and two
   stale entries: `tools/dangling_doc_refs.py: 1 (baseline 2)`,
   `tools/formal_isa_census.py: 0 (baseline 1)`.

## Expected

`suite-self-test` is a `check` job, so `make gate` is red until these rows
are green. The residue row is a one-line census entry per file; the estate row
is a registration (or, for a genuinely unrunnable file, an `UNREGISTERED`
entry with a reason); the dangling citations should name the bug or the
commit rather than the moved doc (see the `--ratchet` message), or the
baseline should be rewritten after reading the diff.

## Next step

1. Register `test_interp_list_ctor.py` and `test_module_globals_compiled.py`
   (they pin landed interpreter behaviour: `INTERP_list_ctor_wraps_its_iterable`
   and module-global compilation) and add the three missing census rows.
2. Rewrite the `bugs/mid/...` citations in the citing docs to the new
   `bugs/...` paths (or to the bug names, where the doc was deleted rather
   than moved).
3. Re-run only `python3 tools/memslot.py --gb 8 --label suite-selftest --
   python3 test_suite.py` and delete this doc when it is green.
