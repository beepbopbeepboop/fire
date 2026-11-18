# SUITE: master lands two test files that nothing runs, so `test_suite.py` is red

`python3 test_suite.py` on master (2026-11-17, `work-7561`, after 24 commits
since `cc11beb3d`) reports 1 failure:

    - the estate: every test file is run by something, or says why not: not run
      by any registered spec, not in UNREGISTERED, and in no declared family:
      test_import_overload_choice.py, test_out_param_local.py

Both files are TRACKED on master and run correctly on their own:

    test_import_overload_choice.py   added by ace3c66b1 ("imports: name the
        overload a call selects when the scan recorded a stub")
    test_out_param_local.py          added by bb3aaf229 ("out parameters: local
        free functions write their result to the caller")

Neither appears in `tools/suite.py`'s registry nor in `test_suite.py`'s
`UNREGISTERED` table (both searched), so the estate check counts them as
orphans. This is not this worktree's doing: the two commits are on master and
the files are untouched here.

Expected: every `test_*.py` on disk is either registered in `tools/suite.py`,
named in `test_suite.py`'s `UNREGISTERED` with a reason, or matched by a
declared family -- that is the check's contract, and it is what keeps a
regression pin from landing unrun.

Next step (owner: the landings for imports/out-parameters, not the dylib
formal lane this doc was filed from):

1. Decide per file whether it is cheap enough to run every `check` -- both
   look like small `fire.py build`/run probes -- and either `test(...)` it in
   `tools/suite.py` (with its measured class) or add it to `UNREGISTERED` with
   the reason. Do not do both.
2. Re-run `python3 test_suite.py`; the estate row is the only expected red.
3. `CODEGEN_stdlib_dylib_lazy_undefined_refs.md` is the doc those two landings
   worked from; its Status already describes the cases, so this doc is only the
   registration follow-up, not a second copy of that bug.
