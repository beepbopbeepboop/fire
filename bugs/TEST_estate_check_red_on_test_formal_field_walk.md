# TEST_estate_check_red_on_test_formal_field_walk: `test_formal_field_walk.py` is in neither the registry nor `UNREGISTERED`, so `suite-self-test` is red

## Status

OPEN, and PRE-EXISTING ON MASTER — measured 2026-10-04 on
`work/merge-formal20` (the merge of `work/formal19-5` and `work/formal18-2`),
which added no test file and did not cause it. Not fixed here: the fix is a row
in `tools/suite.py` or an entry in `test_suite.py`'s `UNREGISTERED`, and both
files are outside this branch's claim (`merge:formal20`).

This is the THIRD time this one check has been red on this tree, and the two
earlier instances are closed — which is the useful part of this filing, because
it says the check is working and the rows were owed, not that the check is
wrong:

| doc | files it named | where they are now |
|---|---|---|
| `TEST_estate_check_red_on_two_form3_test_files.md` | `test_formal_read_before_store.py`, `test_formal_receiver_spelling.py` | registered: `formal-read-before-store`, `formal-receiver-spelling` |
| `TEST_estate_check_red_on_five_hostmod_test_files.md` | `test_formal_admitted.py`, `test_formal_fcntl.py`, `test_formal_math.py`, `test_formal_shutil.py`, `test_formal_stat.py` | registered: `formal-admitted`, `formal-fcntl`, `formal-math`, `formal-shutil`, `formal-stat` |

Both of those docs are therefore candidates for deletion under CLAUDE.md's rule
("a doc for a bug that is fully fixed is deleted, not left behind with a Status
history"), and neither is deleted here because neither was fixed here.

## What I ran, and what it saw

    $ python3 tools/memslot.py --gb 8 --label suiteselftest -- python3 test_suite.py
    ...
    Results: 298 passed, 1 failed
      - the estate: every test file is run by something, or says why not:
        not run by any registered spec and not in UNREGISTERED:
        test_formal_field_walk.py

`suite-self-test` is registered in `check`, `gate` and `smoke`, so this is a red
in the everyday loop and not a by-hand failure.

## Why it is pre-existing, and not inferred

The file is on master and nothing on master accounts for it:

    $ git cat-file -e master:test_formal_field_walk.py && echo YES
    YES
    $ grep -n "test_formal_field_walk" tools/suite.py test_suite.py
    (no output)
    $ git show master:test_suite.py | grep -c "test_formal_field_walk"
    0

Same input, same expectation, same verdict — so master's own `test_suite.py`
reports this one file too. Neither branch under merge touched it:

    $ git diff --name-only master...work/formal19-5 | grep field_walk   # (nothing)
    $ git diff --name-only master...work/formal18-2 | grep field_walk   # (nothing)

## The next step, exactly

Decide between the two halves of the estate rule, which is the same judgement
the two closed instances above each had to make:

* **Register it.** `formal/field_walk` beside `formal-frame-len`, `mem='tiny'`,
  `deps=['preflight']`. What it costs is a measurement nobody has taken on this
  tree, and that measurement is the whole decision — CLAUDE.md's rule is that
  `expect=`/`disabled=` is decided by cost, and the same rule says a file with
  no gate is a file nobody runs, so "cheap" answers it and "minutes per case"
  does not.
* **List it in `UNREGISTERED`** with a reason, the way the ~15 formal
  per-construct suites are listed with `_FORMAL_SUITE_REASON`. That is honest
  but it is a coverage hole written down, so it is the second choice.

Whichever is chosen, do it for this file alone: the check reports one name at a
time, and the seven names before it were each resolved by their own row.
