# FORMAL_test_formal_run_two_cases_red_on_master: two cases in test_formal_run.py fail

Found while merging master into `work/fix-merge-bug-formal-formal-a-for-range-target-may` (2026-11-03).

## What I ran

`python3 tools/memslot.py --gb 8 --label formal-run-range -- python3 test_formal_run.py`
on the merged tree. Result: `formal run: PASS=1344 FAIL=2`.

## What I saw

1. `limit_ellipsis_function_body` (test_formal_run.py ~line 2199): `--backend=arm64` refuses
   `def slen(value): ...` with a returnless-call message ("CPython printed `None` where this path
   printed `0`") rather than the `no body to lower` text the pin expects.
2. `tag-generator` (test_formal_run.py ~line 26934): the import-closure walk reports unresolved
   host modules `builtins, collections, copy, importlib, multiprocessing`, and the file's
   1043 build-and-run rows are dropped with it.

## Why this is not the merge

The merged `formal/model/__init__.py`, `_model_original.py`, `formal/model.py` and both test files
are AST-identical to master's (comments and docstrings ignored). The merge changed only comments.
So both failures reproduce on master's code; they were not introduced by the merge.

## Expected

Both cases pass. Either the code or the pin is wrong; decide which by reading the refusal the
backend is meant to give for a returnless `...` body (`slen`) and the import the closure walk is
meant to be able to answer.

## Next step

1. Run `python3 tools/memslot.py --gb 8 --label x -- python3 test_formal_run.py` on master and
   confirm the same two FAIL lines (the AST argument above is strong, but the run is the proof).
2. For `limit_ellipsis_function_body`: `git log -S"no body to lower" -- formal/model` to find the
   commit that changed the refusal text; then either restore the message or update the pin to the
   returnless wording, and say which in the commit.
3. For `tag-generator`: decide whether those five host modules belong in the sweep's
   `not-answerable/host-import` set (then the closure walk should accept them) or whether a file in
   the closure now imports something new (`git log -p -S"import multiprocessing" -- formal`).
