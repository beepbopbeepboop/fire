# The estate check only sees files named `test_*.py`, so four `*_test.py` files are outside the inventory entirely

## Status

OPEN — found 2026-09-30 while registering the eight unregistered formal test
files, and re-measured after the merge with master, which is where the count
went from two files to four. Not caused by that work and not fixed by it; the fix
widens the estate's subject set, which is a decision about what the check means,
not a registration.

**Step 2 below is now HALF done**, and that is the one thing a reader needs to
know before starting: `suite-self-test`'s `extraglob` is `**/test_*.py` and
`checked_run.expand_globs` drops the same derived directories the walk does, from
one shared list (`checked_run.DERIVED_DIRS`). What is left is the second
SPELLING, and it is not a one-line change — see the next step.

## What is believed

`test_suite.py`'s estate check is "every `test_*.py` in the repo is named by a
registered spec, or is in a list that says why not". The walk behind it
(`_test_files_in_repo`) requires the filename to both start with `test_` and end
with `.py`:

```python
if fn.startswith('test_') and fn.endswith('.py'):
```

So a test file under any other spelling is not unregistered, not excused, and
not counted — it is simply not in the inventory. This repo uses both spellings,
and there are four files under the other one:

    formal/x86_64_endtoend_test.py       -> registered as formal-x86-endtoend
    formal/x86_64_model_coverage_test.py -> registered as formal-x86-model
    formal/x86_64_model_test.py          -> in NO spec and in NO list
    scripts/bootstrap_full_test.py       -> in NO spec and in NO list

The first two are found by the `named` half of the check and not by the `on_disk`
half, which is how the mismatch shows up at all. The second pair is the worse
half: they are outside the inventory in BOTH directions, so nothing counts them
and nothing checks them.

## What was run, and what it saw

Re-measured on the merged tree, 2026-09-30:

    $ python3 - <<'PY'   # the two halves of the check, counted separately
    ...                   # on_disk = _test_files_in_repo()
                          # named   = basenames any spec's cmd mentions
    PY
    on disk              : 101
    named by a spec      : 69
    NAMED BUT NOT ON DISK: ['x86_64_endtoend_test.py',
                            'x86_64_model_coverage_test.py']

    $ python3 test_suite.py | grep 'the estate:'
    the estate: 101 test files, 69 of them run by a registered spec,
                34 declared with a reason, 0 undeclared

69 + 34 does not add to 101, and that is the whole finding: the two counters are
measuring different sets. 69 counts `named`, which includes the two files the
walk never saw.

## Why it matters

The check exists because 50 test files were once named by no registered spec,
and the failure it is modelled on (`CLAUDE.md`'s `coro` story) was a suite
reporting 0/20 for two rounds because nobody noticed. A file outside the
inventory is exactly as unprotected as an unregistered one — with the added
difficulty that the inventory does not know it is missing.

There is a live consequence today beyond the tidiness.
`formal/x86_64_endtoend_test.py` and `formal/x86_64_model_coverage_test.py` are
the x86-64 whole-run and model-coverage suites, both in `proofs`, both
`deps=['preflight', 'prooflib']` and both in the `x86` bucket. If either is
renamed or deleted, the estate check will not say so: a deletion leaves a
registered spec pointing at nothing, and a rename leaves a spec running a path
that is not there. Nothing in the tree checks either.

The two unregistered ones are worse and they are not hypothetical.
`formal/x86_64_model_test.py` is the x86-64 machine-model check — it builds every
`formal/examples/*.mojo` for x86-64, runs the image under Rosetta and compares
the value left in RAX with `x86_exec_exit` in the Lean interpreter. That is the
only check on `lib/X86.lean` that means anything (a machine model that has only
been typechecked proves nothing), and it runs by nothing.
`scripts/bootstrap_full_test.py` is a report generator rather than a test: it
shells out to the bootstrap stages and prints a summary, with a 30 s timeout per
subprocess. It wants an `UNREGISTERED` entry with that reason.

## The next step, exactly

1. Widen the subject set in `_test_files_in_repo` to both spellings this repo
   actually uses — `test_*.py` and `*_test.py` — deriving the two from ONE
   predicate so the walk and any future reader cannot disagree about what a
   "test file" is. `DERIVED_DIRS` is already shared with `checked_run.py`, so
   the exclusion half of this is done; what is left is the spelling.
2. Widen `suite-self-test`'s `extraglob` to `**/*_test.py` in the SAME commit,
   or the check `the estate: every pattern is recursive` / `the glob and the
   walk agree on the subject set` fails on a subject set the walk has just grown.
   The recursive form and the `DERIVED_DIRS` skip that step 2 originally asked
   for are both in place; adding the second pattern is the whole remainder.
3. Decide the two files that widening REVEALS, before or with the widening —
   the order matters, because widening is what makes them visible:
   - `scripts/bootstrap_full_test.py` → an `UNREGISTERED` entry saying it is a
     report generator with no assertions, not a test. Cheap and correct.
   - `formal/x86_64_model_test.py` → register it. It is real coverage of the
     Lean model and it belongs in `x86` beside `formal-x86-endtoend`, with
     `deps=['preflight', 'prooflib']` and a MEASURED memclass row. It has to be
     measured by running it (it builds every x86-64 example), which is a
     whole-sweep run; do not assign a class from its shape, which is what this
     doc exists partly to prevent.
4. Then, separately and not as part of this: the two-sided check that would
   catch a registered spec naming a file that is not there — the mirror of
   `the estate: no excuse for a file that is now registered`. Right now
   `named - on_disk` is computed by nothing at all; it fell out of the
   arithmetic above. A spec whose `cmd` names a `test_*.py` that does not exist
   is a broken registration and should say so. `formal/x86_64_model_test.py`
   and `scripts/bootstrap_full_test.py` are what this check would have caught on
   the day they landed.

Step 4 is the one with the value; steps 1-3 are what make it possible to write.
Do not do step 4 alone: with the subject set as it is, it would pass vacuously
for the files this doc is about.

## Related

- `checked_run.py`'s `_hash_input` and `expand_globs` now share one skip rule
  (`DERIVED_DIRS` + `is_derived_dir`), and `test_suite.py`'s walk reads it too —
  so the two walks cannot drift about what a test file is, which is the failure
  that let `test_llm/test_llm.py` be found by the walk and invisible to the
  cache key.
- Found while registering the eight files in
  `bugs/UNTESTED_estate_check_is_red_and_outside_the_gate.md` (closed and
  deleted 2026-09-30), whose own arithmetic is where `62 + 33 != 93` showed up.
- `bugs/TEST_registered_tests_in_no_bucket_never_run.md` is the same family of
  hole one level down — a registration that satisfies the estate without being in
  a run — and is why "the walk found it" is not the same claim as "it runs".
