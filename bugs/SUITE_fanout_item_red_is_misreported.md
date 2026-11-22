# A red fanout ITEM is unaddressable and misreported: bogus `first bad`, and "no bug doc tracks this job"

**Status:** partly fixed 2026-11-21. Symptom 2 — `known_bugs()` could not match a per-item doc, so the
gate printed `NEW: no bug doc tracks this job` for a fanout whose fifty items each had one — is FIXED
and pinned below. Symptom 1 — the fabricated `first bad` — is still open and is now tracked with its
sibling causes in `SUITE_ledger_counts_a_skip_as_green.md` (sites 1-2: `reconcile` takes an absent job
as green, and both probe readers decide from an exit code), which owns the tri-state reader.

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

1. **The ledger bisect is vacuous. STILL OPEN** (owned by
   `SUITE_ledger_counts_a_skip_as_green.md`). `tools/verify_landed.py::job_is_red_at(job, sha)`
   runs exactly that command and reads "non-zero" as "red at this commit", so for a
   fanout item every probed commit is red and `gate_ledger.first_bad` returns the
   earliest commit in `last_good..sha`. Measured: the ledger wrote
   `first bad 0b0316114e, last good d0c0a1cc57` into every one of the fifty docs, and

       git rev-list --first-parent --reverse d0c0a1cc57..c0182fd365 | head -1
       0b0316114e0d35c773c8114882876a7485ac829e

   `0b0316114e` is simply the first of the four commits in that range. So the
   "First known not working" line in all fifty `gate-bootstrap-stage2-dumps:*.md`
   docs was an artifact, not a bisection — the docs' own repro command was the thing
   that exits 1. The fix is the tri-state reader that doc's next step 1 describes
   (`job_is_red_at` returning NO EVIDENCE for a name the suite will not run, and
   `bisect_job` stopping with a note instead of picking a commit); it is not duplicated
   here.

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
  **Open** (symptom 1, owned by `SUITE_ledger_counts_a_skip_as_green.md`).
- the gate's `NEW` line resolves the doc(s) that track the failed job, including the
  per-item docs of a fanout. **Done** (symptom 2 above).

## Exact next step

1. Symptom 1: land the tri-state reader in `SUITE_ledger_counts_a_skip_as_green.md`
   next step 1 (its site 2 is exactly this caller). Nothing else remains here.
2. Re-run `python3 tools/test_gate_ledger.py`, `python3 tools/test_gate_doc.py` and
   `python3 test_suite.py` after that change; no gate job's runtime changes.

Not urgent while `bootstrap-stage2-cc` is doc'd off (since 416ed660c the whole fanout
SKIPs and the parent never reaches the `FAILED` section), but it is exactly what will
mislead the fifty tasks when the fanout is red for a real reason.
