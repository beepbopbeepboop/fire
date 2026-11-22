# `test_imported_global_stub.py`: a function-scoped `from module_loader import STDLIB_PATH` emits the weak stub on master

**Test:** `test_imported_global_stub.py::test_function_scoped_str_global_reads_accessor_not_stub`
(run with `python3 -c "import test_imported_global_stub as t; t.test_function_scoped_str_global_reads_accessor_not_stub()"`,
or the file under `tools/memslot.py --gb 8`). It is unchanged between master and
`work/bug-gate-bootstrap-stage2-cc-3`, and it is RED on master.

## What is seen (master, 2026-11-22)

`gimple_codegen.compile_to_gimple(STDLIB_SRC, do_imports=False)` emits the
weak "unavailable in compiled mode" stub instead of the defining module's
accessor:

    extern int64_t STDLIB_PATH (...);  /* from module_loader */
    static void * _funcptr_STDLIB_PATH = (void *)STDLIB_PATH;
      _t2 = _funcptr_STDLIB_PATH;

The test requires `_funcptr_STDLIB_PATH` and `extern int64_t STDLIB_PATH` to be
absent and `module_loader__mojo_global_get_STDLIB_PATH` to be present. The
`bugs/hard/GATE_red_recover-land_2026-11-02-part5-part2.md` split note says this
exact sibling was fixed and its doc deleted, so this is a regression (or a
test that stopped matching a later change), not an open-never-fixed bug.

## What is known

* Not caused by `module_loader.py`'s `_ml_py_global_ctype` (the str-literal
  export change from `work/bug-gate-bootstrap-stage2-cc-3` was applied on
  master while measuring this; the case stays red).
* `work/bug-gate-bootstrap-stage2-cc-3` at `86d5add94` PASSES this case on its
  own tree (measured 2026-11-22, detached worktree, same test file). That
  branch's extra changes are in `gimple_codegen.py` (`_quick_type` fallback to
  `_imported_src_def_return_type`), `mojo/backend_gimple/emit_funcs.py`
  (`_definer_walk_context`) and `mojo/backend_gimple/module_gen.py`. Which of
  them flips this case was NOT isolated.

## Next step

1. Bisect master's history for the commit that turned this case red. The case
   runs in ~2 s, so `git bisect run` over a `python3 -c` one-liner that exits
   non-zero when `_funcptr_STDLIB_PATH` appears in
   `compile_to_gimple(STDLIB_SRC, do_imports=False)` is cheap. Use a detached
   worktree, not a checkout of the user's tree.
2. Fix the regressing change at its cause. Do not special-case the name
   `STDLIB_PATH`.
3. The quick proof is the case above passing with the whole file green.
