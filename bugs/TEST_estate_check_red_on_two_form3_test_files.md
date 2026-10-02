# TEST_estate_check_red_on_two_form3_test_files: two test files are in neither the registry nor `UNREGISTERED`, so `suite-self-test` is red

## Status

OPEN, and PRE-EXISTING ON MASTER — found 2026-10-02 while merging
`work/merge-bugs-batch` into master's formal3 batch (`work/merge-bugs2`). Not
caused by that merge and not fixed by it: both files arrived with master, and
master's own `test_suite.py` reports exactly the same two. Measured, not
inferred — see the transcript below.

## What was run, and what it saw

    $ /opt/homebrew/bin/python3 test_suite.py
    ...
    Results: 282 passed, 1 failed
      - the estate: every test file is run by something, or says why not:
        not run by any registered spec and not in UNREGISTERED:
        test_formal_read_before_store.py, test_formal_receiver_spelling.py

`suite-self-test` is registered in `check`, `gate` and `smoke`, so this is a red
in the everyday loop, not a by-hand failure.

Both files came from master:

    $ git log --oneline --diff-filter=A master -- \
        test_formal_read_before_store.py test_formal_receiver_spelling.py
    44e90eec formal: ONE rule for 'does this method take a receiver' — model.method_receiver_name
    1cfa8f80 formal: a one-field mutator hands its receiver back, and a name read
                 before any path stores it is refused

and neither side of the estate accounted for them:

    $ git show master:tools/suite.py | grep -c 'read_before_store\|receiver_spelling'
    0
    $ git show master:test_suite.py | grep -c 'read_before_store\|receiver_spelling'
    0

## What is believed

The check is the estate one: every `test_*.py` in the repo is named by a
registered spec, or is in `UNREGISTERED` with a reason. It is exactly the
mechanism this project's rules ask for — "an unaccounted-for test file is a hole
in coverage" — and it is the only thing standing between a test file and
silence. Two files landed without going through it, so the machinery that exists
to catch that is reporting it, correctly.

## The next step, exactly

**Both files belong in the registry, not in `UNREGISTERED`.** They are both
cheap and both PASS on this tree, measured:

| file | wall | peak | verdict |
|---|---|---|---|
| `test_formal_read_before_store.py` | 10.9 s | 0.0 GB | `read-before-store: PASS=61 FAIL=0` |
| `test_formal_receiver_spelling.py` | 6.0 s | 0.1 GB | `formal receiver spelling: PASS=3 FAIL=0` |

So the next step is two `test(...)` rows in `tools/suite.py`, `mem='tiny'`,
`cache=True`, and a bucket each — and the bucket is the only real decision:

* `test_formal_read_before_store.py` is a pure unit test: it calls
  `formal/model.py`'s `read_before_store` on parsed function bodies and asks
  CPython for the same verdict in a subprocess per case. **No build, no image.**
  Its own module docstring says so ("as a call into `read_before_store` it is
  microseconds, so all of them are here and the whole file costs no builds at
  all"), and the 10.9 s is 61 CPython subprocesses. `check` is the right home.
* `test_formal_receiver_spelling.py` DOES build and run images (it calls
  `fire.py build --formal` per case), so it is the same shape as the ~15 files
  that carry `_FORMAL_SUITE_REASON` in `UNREGISTERED`. Whether to register it
  or to list it with that reason is a judgement about the proofs bucket's cost,
  not a mechanical step — and `bugs/COMPILE_FAIL_estate_check_red_for_eleven_formal_suites.md`
  is the write-up of what closing the estate gap for that shape costs.

Do NOT reach for `UNREGISTERED` on the first file just because it is the
smaller edit: it is the cheapest, highest-value test of the two, it guards the
soundness direction of a refusal rule (a refusal the language would not have
made breaks a program that runs), and a file with no gate is a file nobody
runs. Prefer registering over marking, which is the project's own rule.

## Note for whoever merges next

`suite-self-test`'s `extra` includes `extraglob=['**/test_*.py']`, so this
check re-runs for any change to any test file — adding a test file without
accounting for it is a red that appears in a PR that only added a test.