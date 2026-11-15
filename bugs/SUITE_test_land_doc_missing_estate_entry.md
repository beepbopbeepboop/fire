# `test_suite.py`'s estate check is red on `tools/test_land_doc.py`

Class: one line. `tools/test_land_doc.py` landed in 62411916c but no
`UNREGISTERED` entry and no registered spec names it, so the estate check
(`test_suite.py`, `test_every_test_file_is_registered`) reports it.

## What I ran

    python3 -c "import test_suite; test_suite.test_every_test_file_is_registered()"

## What I saw

    FAIL  the estate: every test file is run by something, or says why not:
          not run by any registered spec, not in UNREGISTERED, and in no
          declared family: tools/test_land_doc.py
          ... 1 undeclared ...

## What I expected

No `FAIL` line, as on fa105c747 for every other file.

## Exact next step

Either register `tools/test_land_doc.py` in `tools/suite.py` in the bucket
that runs the land/doc tools, or add it to `test_suite.py`'s `UNREGISTERED`
with a reason (the file is a small direct-run check, so a
`_STANDALONE_TEST_REASON`-style entry fits). Then `python3 test_suite.py`
should have no FAIL line and the estate census should read `0 undeclared`.
