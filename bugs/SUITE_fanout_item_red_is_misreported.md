# A red fanout ITEM is unaddressable and misreported: bogus `first bad`, and "no bug doc tracks this job"

**Status:** open. Found 2026-11-21 while working the doc
`bugs/gate-bootstrap-stage2-dumps:test_jit.mojo.md` (deleted in the same commit: the
job's red was the disabled-producer cascade fixed by 416ed660c, not a defect of
`test_jit.mojo`). Neither symptom below is specific to that item; all fifty
`bootstrap-stage2-dumps:<file>` items hit both.

## What I ran, and what I saw

A fanout ITEM — a job named `<parent>:<file>` — has no `test()`/`fanout()` call of
its own, so `tools/suite.py <parent>:<file>` cannot select it:

    $ python3 tools/suite.py bootstrap-stage2-dumps:test_jit.mojo
    suite.py: no such bucket or test: 'bootstrap-stage2-dumps:test_jit.mojo'
    ... exit 1

That is correct for an interactive selection (and `gate_ledger.registered()` now says
so), but two callers assume the name is runnable:

1. **The ledger bisect is vacuous.** `tools/verify_landed.py::job_is_red_at(job, sha)`
   runs exactly that command and reads "non-zero" as "red at this commit", so for a
   fanout item every probed commit is red and `gate_ledger.first_bad` returns the
   earliest commit in `last_good..sha`. Measured: the ledger wrote
   `first bad 0b0316114e, last good d0c0a1cc57` into every one of the fifty docs, and

       git rev-list --first-parent --reverse d0c0a1cc57..c0182fd365 | head -1
       0b0316114e0d35c773c8114882876a7485ac829e

   `0b0316114e` is simply the first of the four commits in that range. So the
   "First known not working" line in all fifty `gate-bootstrap-stage2-dumps:*.md`
   docs is an artifact, not a bisection — the docs' own repro command is the thing
   that exits 1.

2. **`known_bugs()` cannot match a per-item doc to anything.** `tools/suite.py:6647`
   splits the JOB name on `[-_]` but the doc FILENAME on `[-_.]`, and the fanout
   item's name puts the file after a colon:

       name words: bootstrap-stage2-dumps:test_jit.mojo -> ['bootstrap','stage2','dumps:test','jit.mojo']
       file tokens: gate-bootstrap-stage2-dumps:test_jit.mojo -> {..., 'dumps:test', 'jit', 'mojo'}

   Neither the item name nor the parent name matches, even though the doc exists:

       >>> known_bugs('bootstrap-stage2-dumps')                 == []
       >>> known_bugs('bootstrap-stage2-dumps:test_jit.mojo')   == []   # doc present on disk

   so gate `c0182fd3` printed, for a fanout whose fifty items all had docs,

       FAILED:
         bootstrap-stage2-dumps  (1s)
             NEW: no bug doc tracks this job

   and would print it again for any fanout that goes red later, sending a "NEW"
   regression signal when the per-item docs are the record it is asking for.

## Expected

- A red fanout item either has a real bisection or explicitly reports that it could
  not be bisected ("an item of `<parent>`; the parent's registration is the unit"), and
- the gate's `NEW` line resolves the doc(s) that track the failed job, including the
  per-item docs of a fanout.

## Exact next step

1. `tools/suite.py`: normalize in `known_bugs` — split BOTH the name and the filename
   token on `[-_.:]` (or compare on a normalized key with `:`/`.` stripped), so
   `known_bugs('bootstrap-stage2-dumps:test_jit.mojo')` returns
   `bugs/gate-bootstrap-stage2-dumps:test_jit.mojo.md`. Add a case to
   `tools/test_suite.py` (or wherever `known_bugs` is covered) for the fanout-item
   spelling and for the parent spelling.
2. `tools/verify_landed.py::job_is_red_at` / `bisect_job`: test `G.registered(src, job)`
   first. For an item, either select it through the parent (`suite.py` needs a way to
   run one item, e.g. accept `<parent>:<item>` in `walk()` and filter the fanout's
   `items`) or record `bisect_note = "an item of `<parent>`; not individually
   bisectable"` and skip the bisect instead of claiming `first_bad` at the range's
   first commit. Punching `git bisect` on an item must never again write a fabricated
   "first not working" sha into a worker's task.
3. Re-run `python3 tools/test_gate_ledger.py`, `python3 tools/test_gate_doc.py` and
   `python3 tools/test_suite.py` after either change; no gate job's runtime changes.

Not urgent while `bootstrap-stage2-cc` is doc'd off (since 416ed660c the whole fanout
SKIPs and the parent never reaches the `FAILED` section), but it is exactly what will
mislead the fifty tasks when the fanout is red for a real reason.
