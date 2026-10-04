# `suite-self-test`'s UNREGISTERED estate check is red on five more test files

**What I ran.** `python3 test_suite.py` (the registry self-test, 48 s).

**What I saw.** 282 passed, 1 failed:

```
the estate: every test file is run by something, or says why not:
  not run by any registered spec and not in UNREGISTERED:
  test_formal_admitted.py, test_formal_fcntl.py, test_formal_math.py,
  test_formal_shutil.py, test_formal_stat.py
```

**What I expected.** Green.

**Why it is red, and that it is not this change's.** Five host-module test
files reached master through the `formal5-hostmods-*` / `formal6-*` batches
(`test_formal_math.py` arrived in `63fe3b21`, "shutil: copy, move, rmtree,
copytree and which, over the real filesystem"). `test_suite.py`'s
`UNREGISTERED` table has a row for the older instance of this same check
(`TEST_estate_check_red_on_two_form3_test_files`, two files) and these
five were never added to it. Confirmed pre-existing rather than inferred:
`git merge-base --is-ancestor` puts every one of them in this branch's history,
i.e. they came in with the base commits, and the working tree change that
touched the test estate (`test_formal_sweep_truth.py`, an already-registered
file) added no new file.

**Exact next step.** Either (a) add the five names to `UNREGISTERED` in
`test_suite.py` with the reason the other formal per-construct suites carry
(`_FORMAL_SUITE_REASON` — they build and RUN images on both architectures
against CPython, so a gate row costs minutes per file), or (b) register the ones
that are cheap now that `math`, `stat`, `fcntl`, `shutil` and `admitted` have
landed. Which of the five are cheap is a measurement nobody has taken on this
tree, and this is the integrator's call, not a worker's.

**Do not fix it by deleting a test or by adding the files to a bucket that
cannot afford them.** A `DISABLED`/`UNREGISTERED` row with a reason is the
honest state; a bucket entry that times out is a gate that costs tens of
minutes and reports a machine problem as a test failure.
