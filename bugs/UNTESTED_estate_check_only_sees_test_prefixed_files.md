# The estate check only sees files named `test_*.py`, so two registered test files are outside the inventory entirely

## Status

OPEN — found 2026-09-30 while registering the eight unregistered formal test
files. Not caused by that work and not fixed by it; the fix widens the estate's
subject set, which is a decision about what the check means, not a registration.

## What is believed

`test_suite.py`'s estate check is "every `test_*.py` in the repo is named by a
registered spec, or is in a list that says why not". The walk behind it
(`_test_files_in_repo`) requires the filename to both start with `test_` and end
with `.py`:

```python
if fn.startswith('test_') and fn.endswith('.py'):
```

So a test file under any other spelling is not unregistered, not excused, and
not counted — it is simply not in the inventory. There are two such files in the
tree today, and both are registered, so nothing is red:

    formal/x86_64_endtoend_test.py       -> registered as formal-x86-endtoend
    formal/x86_64_model_coverage_test.py -> registered as formal-x86-model

The two are found by the `named` half of the check and not by the `on_disk`
half, which is how the mismatch shows up at all.

## What was run, and what it saw

    $ python3 - <<'PY'   # the two halves of the check, counted separately
    ...                   # on_disk = _test_files_in_repo()
                          # named   = basenames any spec's cmd mentions
    PY
    on disk              : 93
    named by a spec      : 62
      of those, on disk  : 60
      NAMED BUT NOT ON DISK: ['x86_64_endtoend_test.py',
                              'x86_64_model_coverage_test.py']

    $ python3 test_suite.py | grep 'the estate:'
    the estate: 93 test files, 62 of them run by a registered spec,
                33 declared with a reason, 0 undeclared

The 62 and the 33 do not add to the 93, and that is the whole finding: the two
counters are measuring different sets. 62 is a count of `named`, which includes
two files the walk never saw.

## Why it matters

The check exists because 50 test files were once named by no registered spec,
and the failure it is modelled on (`CLAUDE.md`'s `coro` story) was a suite
reporting 0/20 for two rounds because nobody noticed. A file outside the
inventory is exactly as unprotected as an unregistered one — with the added
difficulty that the inventory does not know it is missing.

There is a live consequence today beyond the tidiness. `formal/x86_64_endtoend_test.py`
and `formal/x86_64_model_coverage_test.py` are the x86-64 whole-run and
model-coverage suites, both in `proofs`, both `deps=['preflight', 'prooflib']`
and both in the `x86` bucket. If either is renamed or deleted, the estate check
will not say so: a deletion leaves a registered spec pointing at nothing, and a
rename leaves a spec running a path that is not there. Nothing in the tree
checks either.

## The next step, exactly

1. Widen the subject set in `_test_files_in_repo` to both spellings this repo
   actually uses — `test_*.py` and `*_test.py` — and derive the two from one
   predicate so the walk and any future reader cannot disagree about what a
   "test file" is. `build/` , `__pycache__`, `aside/`, `bside/` and dot
   directories stay excluded for the reason the existing docstring gives.
2. Widen `suite-self-test`'s `extraglob` to match, in the SAME commit, because
   the new check `the estate: every test file is where the glob can see it` will
   otherwise fail: both new files are in `formal/`, and the pattern is flat.
   The pattern has to be recursive (`**/test_*.py`, `**/*_test.py`) AND the
   expansion has to exclude the same directories the walk does, or
   `build/`, `aside/` and `bside/` re-enter the subject set and the cache key
   starts depending on a derived tree. `checked_run.expand_globs` is where that
   exclusion belongs, next to the `__pycache__`/`*.pyc` skip `_hash_input`
   already does for directories.
3. Consider, separately and not as part of this: the two-sided check that would
   catch a registered spec naming a file that is not there — the mirror of
   `the estate: no excuse for a file that is now registered`. Right now
   `named - on_disk` is computed by nothing at all; it fell out of the
   arithmetic above. A spec whose `cmd` names a `test_*.py` that does not exist
   is a broken registration and should say so.

Step 3 is the one with the value; steps 1 and 2 are what make it possible to
write. Do not do step 3 alone: with the subject set as it is, it would pass
vacuously for the two files this doc is about.

## Related

- `checked_run.py`'s `_hash_input` already skips `__pycache__` and `*.pyc` when
  hashing a directory, and `expand_globs` does not skip anything — the exclusion
  rule step 2 needs already exists once and has to be reused rather than
  written a second time with a different directory list.
- Found while registering the eight files in
  `bugs/UNTESTED_estate_check_is_red_and_outside_the_gate.md` (closed and
  deleted 2026-09-30), whose own arithmetic is where `62 + 33 != 93` showed up.
