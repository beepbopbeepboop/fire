# SUITE `suite-self-test` is red on master (registry, estate, doc refs)

**Job:** `suite-self-test`. Found by the merge lane
`fix-merge-bug-mid-diagnostics-trait-conformance-pa-3`; re-measured
2026-11-14 by the merge lane
`fix-merge-fix-merge-bug-formal-svc-exit-handling-incomplete` on the merged
tree at master `b51a76057`. Nothing this branch touched is among the rows:
`tools/suite.py` and `test_suite.py` are byte-identical to master's, and a
pristine `master` snapshot run reproduces the same rows.

Reproduce:

    python3 tools/memslot.py --gb 8 --label suite-selftest -- python3 test_suite.py

Result on the merged tree (`b51a76057`): `381 passed, 6 failed`.

## Status

- 2026-11-14, `work/bug-suite-self-test-red`: the previous attempt's six
  commits fix rows 1, 2, 3 and 5 (self-host key, the disabled section, and the
  admission row now uses a non-disabled job), and a run on top of them
  measures `394 passed, 2 failed`. Row 4 is down to one file —
  `test_mojoc_implicit_default_conformance.py`, which landed on master after
  that attempt's last merge — and row 6 is the other.
- Row 4's file is in-process (writes and reads a `.mojoc`, runs the one
  import-time checker; measured 0.0 GB, sub-second), so it is registered as
  `mojoc-implicit-default-conformance` in `check` and added to
  `test_the_suite_self_test_registrations_are_gated`. That pin FAILS with the
  spec removed and passes with it, which is the regression test for this row.
- Row 6: a real `python3 test_gimple_runner.py` on this branch reports
  `625 passed, 2 failed` — the registry's known
  `c_accessor_helpers_emitted_once_across_modules` plus
  `gimple_or_chain_bool_getattr_dict` (SIGSEGV). This branch is 118 commits
  behind master, whose recorded 2026-11-13 run is `626 passed, 1 failed`; the
  census is corrected to the registry's 1 (the count that run and the marker
  both state), not to this stale tree's 2.

## Failing rows

1. **self-host key: every module fire.py imports is hashed.**
   `not in the key: ['unknown_decl_check.py']` — `899a5d705` made
   `unknown_decl_check.py` reachable from `fire.py` (the compiler-provided
   builtins: `conforms_to`, `constrained`), but the key list in `suite.py` was
   not extended, so the self-host fingerprint is not covering a module it must.

2. **disabled: the real registry has no job that is not run.**
   `['cli-usage-text', 'formal-read-before-store', 'gimple', 'metalgpu']` are
   registered with `disabled=` (their docs are the gate-triage docs
   `bugs/gate-cli-usage-text.md`, `bugs/gate-metalgpu.md`,
   `bugs/gate-gimple.md` and the read-before-store doc), but `test_suite.py`'s
   `disabled` section still asserts the registry has NO disabled job at all.
   Each one has to be named there and its reserves-0 / `--list` / `--dry-run`
   properties re-asserted, the way `ab-native` was until `2f75609d`.

3. **disabled markers: the state the section is written for is stated, not
   assumed.** The sibling of row 2, same four names: the section says "no
   registered job is disabled" and that sentence is now false.

4. **the estate: every test file is run by something, or says why not.**
   Thirteen files are in no registered spec, not in `UNREGISTERED` and in no
   declared family:

       test_binding_evidence.py
       test_codegen_simd_exp_statictuple.py
       test_codegen_yield_from_walk_ast_memo.py
       test_function_body_alias_class_import.py
       test_gpu_offload_validation_part3.py
       test_mojoc_implicit_default_conformance.py
       test_mojoc_import_conformance.py
       test_mojoc_module_import_ambiguous.py
       test_mojoc_synthetic_signature_default.py
       test_stdlib_dylib_lazy_undefined_refs_probes.py
       test_stdlib_syntax_variant.py
       test_unknown_decl_check.py
       tests/test_suite_silentnoop_part1_replan.py

   `test_codegen_simd_exp_statictuple.py` is the newest: it landed with
   `8bdabce60` (the simd/static-tuple bracket-argument fix) and its bug doc was
   deleted with it, but no `tools/suite.py` spec names the test.

5. **admission: ...and an ordinary one reserves its class.** This row uses
   `suite.REGISTRY['gimple']` as its "ordinary job", and `gimple` is now
   disabled, so `reserved_gb` is 0 while its class is not — the assertion
   fires on the registry change in row 2 rather than on the admission code.

6. **expect count: the counts the registry states are the ones the reader
   sees.** The reader now sees

       {'gimplerunner': 1, 'x86-containers': 1, 'formal-dylib': 3,
        'formal-x86-endtoend': 1}

   and the census in `test_suite.py` still states 20 for `gimplerunner`
   (`bugs/hard/SUITE_gimplerunner_21_failing.md` describes a run that prints
   `Results: 592 passed, 20 failed`). Either the registry marker or the census
   must move to the measured count — decide from a real `gimplerunner` run,
   not by editing the number until the check is green.

## Expected

`suite-self-test` is a `check` job, so `make gate` is red until these rows are
green. Rows 2, 3 and 5 are one change (teach the disabled section about the
four live gate-triage jobs); row 1 is one key entry; row 4 is one registration
(or an `UNREGISTERED` reason for a genuinely unrunnable file); row 6 needs a
measured `gimplerunner` count before either side of it is changed.

## Done when

`python3 tools/memslot.py --gb 8 --label suite-selftest -- python3 test_suite.py`
reports `0 failed` — in particular the estate row names no test file, and the
expect-count census agrees with the registry the reader sees
(`gimplerunner: 1`, the count a real `python3 test_gimple_runner.py` run
reports).

## Next step

1. Extend the self-host key in `tools/suite.py` with `unknown_decl_check.py`
   and re-run `test_suite.py`; the import walk is what says whether the key is
   complete.
2. In `test_suite.py`, replace the two "no registered job is disabled"
   assertions with the four live names and their properties (reserves 0,
   `--list` shows the doc, `--dry-run` plans it as disabled); then pick a
   non-disabled job for row 5's admission assertion (`mojoc`'s sibling).
3. Register `test_codegen_simd_exp_statictuple.py` against the simd/codegen
   bucket (it runs in 7 s at 0.1 GB), and triage the other twelve estate rows
   the same way.
4. Run `gimplerunner`, read its summary line, and correct whichever of the
   registry marker and the census disagrees with the run. Then re-run only

       python3 tools/memslot.py --gb 8 --label suite-selftest -- python3 test_suite.py

   and delete this doc when it is green.
