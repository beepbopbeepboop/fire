# A red fanout ITEM is unaddressable and misreported: bogus `first bad`, and "no bug doc tracks this job"

**Status:** fully fixed 2026-11-21. Symptom 2 — `known_bugs()` could not match a per-item doc, so the
gate printed `NEW: no bug doc tracks this job` for a fanout whose fifty items each had one — is FIXED
and pinned below. Symptom 1 — the fabricated `first bad` — is FIXED by the same tri-state reader the
`SUITE_ledger_counts_a_skip_as_green.md` lane landed (its sites 1-3: `reconcile` requires a previous-run
PASS, and both probe readers decide from the suite's per-job verdict line instead of an exit code).

Found 2026-11-21 while working the `bootstrap-stage2-dumps:test_jit.mojo` item doc (deleted in the same
commit: the job's red was the disabled-producer cascade fixed by 416ed660c, not a defect of
`test_jit.mojo`). Neither symptom below was specific to that item; all fifty
`bootstrap-stage2-dumps:<file>` items hit both.

## What I ran, and what I saw

A fanout ITEM — a job named `<parent>:<file>` — has no `test()`/`fanout()` call of its own, so
`tools/suite.py <parent>:<file>` cannot select it:

    $ python3 tools/suite.py bootstrap-stage2-dumps:test_jit.mojo
    suite.py: no such bucket or test: 'bootstrap-stage2-dumps:test_jit.mojo'
    ... exit 1

That is correct for an interactive selection (and `gate_ledger.registered()` now says
so), but two callers assume the name is runnable:

1. **The ledger bisect is vacuous. FIXED 2026-11-21** (by the tri-state reader
   `SUITE_ledger_counts_a_skip_as_green.md` sites 1-3 landed). `tools/verify_landed.py::job_is_red_at(job, sha)`
   runs exactly that command and now reads the suite's own per-job verdict, so for a
   fanout item every probed commit is NO EVIDENCE and `bisect_job` stops with
   `job did not run at <sha>; cannot bisect` instead of picking a commit. Measured before the fix: the ledger wrote
   `first bad 0b0316114e, last good d0c0a1cc57` into every one of the fifty docs, and

       git rev-list --first-parent --reverse d0c0a1cc57..c0182fd365 | head -1
       0b0316114e0d35c773c8114882876a7485ac829e

   `0b0316114e` is simply the first of the four commits in that range.

2. **`known_bugs()` cannot match a per-item doc to anything. FIXED 2026-11-21.**
   `tools/suite.py` split the JOB name on `[-_]` but the doc FILENAME on `[-_.]`, and the fanout
   item's name puts the file after a colon:

       name words (before): bootstrap-stage2-dumps:test_jit.mojo -> ['bootstrap','stage2','dumps:test','jit.mojo']
       file tokens:         gate-bootstrap-stage2-dumps:test_jit.mojo -> {..., 'dumps:test', 'jit', 'mojo'}

   Neither the item name nor the parent name matched, even though the doc existed:

       >>> known_bugs('bootstrap-stage2-dumps')                 == []
       >>> known_bugs('bootstrap-stage2-dumps:test_jit.mojo')   == []   # doc present on disk

   so gate `c0182fd3` printed, for a fanout whose fifty items all had docs,

       FAILED:
         bootstrap-stage2-dumps  (1s)
             NEW: no bug doc tracks this job

   and would print it again for any fanout that goes red later, sending a "NEW"
   regression signal when the per-item docs are the record it is asking for.

   **What landed:** both sides are now split on the same `[-_.:]`, so the item finds
   its `bugs/gate-<parent>:<file>.md` and the parent finds its items' docs.
   `known_bugs(name, bugs_dir=None)` gained the optional corpus root so the matcher is
   tested against a synthetic `bugs/` rather than whatever the live tree holds today;
   the answer still reads `bugs/<doc>.md` for any corpus. Pinned by
   `test_suite.py::test_known_bugs_matches_a_fanout_item_and_its_parent` (an item
   finds its own doc, the parent finds it, an unrelated job claims nothing); it fails
   on the pre-fix splitter, which returned `[]` for both spellings with the doc on
   disk. Note the rule is still "a pointer for the reader, not a verdict": splitting
   the name on `.`/`:` can name one extra related doc (job `fire.py` also reaches
   `gate-...-fire_compiler.py.md`), which is the price of a rule that can see an item
   at all — being told about a near-miss doc beats `NEW` for a documented red.

## Expected

- A red fanout item either has a real bisection or explicitly reports that it could
  not be bisected ("an item of `<parent>`; the parent's registration is the unit").
  **Done** (symptom 1: no-evidence bisect note).
- the gate's `NEW` line resolves the doc(s) that track the failed job, including the
  per-item docs of a fanout. **Done** (symptom 2 above).

## Exact next step

1. Done: the tri-state reader landed in `SUITE_ledger_counts_a_skip_as_green.md`
   next step 1 (its site 2 is exactly this caller), pinned by
   `tools/test_integrate_probe_loop.py::BisectStopsWithoutEvidence`.
2. Re-run `python3 tools/test_gate_ledger.py`, `python3 tools/test_gate_doc.py` and
   `python3 test_suite.py` after that change; no gate job's runtime changes.

Not urgent while `bootstrap-stage2-cc` is doc'd off (since 416ed660c the whole fanout
SKIPs and the parent never reaches the `FAILED` section), but it is exactly what will
mislead the fifty tasks when the fanout is red for a real reason.

## Relationship to the archived branch work/fix-gate-bootstrap-stage2-dumps-bootstrap-test-stress-mojo (2026-11-21)

That branch's one commit (6470f5922, 148 behind this master) is docs-only, and
this DROP is the record that nothing in it is missing from the tree. It added
three files, and each subject already lives somewhere better (the branch's own
paths are deliberately not cited here: they never existed on master, and the
ratchet must not carry citations to docs the tree does not have):

- the per-item doc for `bootstrap_test_stress.mojo` — master deleted the same
  doc in 42865539e once 416ed660c made a disabled producer's dependents SKIP;
  that commit message carries the branch's analysis (the item is not
  independently red; `0b0316114e` is the phantom bisect, not a culprit).
- the branch's fanout-item doc — the first symptom above, including the
  `known_bugs` item-name mismatch and the `set_disabled` no-op (the false
  "Skipped" paragraph that no-op produced is fixed in
  `tools/gate_ledger.py::report_text`, which now names only a marker the ledger
  actually wrote). Its proposed fix
  in `main` (fold `fanout:item` with `k.split(':', 1)[0]`) is the rule
  `failed_jobs` now implements, pinned by
  `tools/test_gate_doc.py::test_one_doc_per_failing_test_not_per_fanout_item`.
- the branch's passed-jobs note — site 3 of
  `SUITE_ledger_counts_a_skip_as_green`, which gives it the shared tri-state
  parser the branch's one-line regex fix would have pre-empted.

Measured on this tree while deciding: `python3 tools/suite.py
bootstrap-stage2-dumps` -> exit 0, "2 passed, 0 failed, 1 skipped, 2 disabled
(5 tests, 99 jobs, 17.3s, peak 0.2 GB)", the fanout SKIPPED naming
`bugs/gate-bootstrap-stage2-cc.md`, so no per-item doc is owed for it now; and
`known_bugs('bootstrap-stage2-dumps:test_jit.mojo')` still returns `[]`, which
is this doc's open symptom 2, not a reason to land a second copy of it.
