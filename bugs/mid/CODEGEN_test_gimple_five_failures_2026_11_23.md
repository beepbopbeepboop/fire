# test_gimple.py: 5 failures on master (2026-11-23), none tracked

`python3 test_gimple.py` on master (2026-11-23): `Results: 470 passed, 5 failed`.

    FAIL generator_kwargs_forward_str_gap_compiles_via_cpp_path: generated .cpp missing char* kwargs-gap lowering
    FAIL every_ast_mutation_site_invalidates_the_walk_memo: 23 problem(s)
         e.g. mojo/backend_gimple/cpp_core.py::_cpp_try_kwargs_forward_call writes an AST node's field
         (`body`) and never invalidates the memo; same for _cpp_dyn_word_lambda,
         _cpp_generator_start_kwargs_expr, ... (23 sites, all in cpp_core.py)
    FAIL a_mixed_iterated_parameter_with_a_str_variable_runs_correctly: the compiled program exited -11 printing '4\n5\n'
    FAIL test_module_level_mixed_iterated_parameter_with_str_variable_runs_correctly: exited -11 printing '4\n5\n'
    FAIL a_str_returned_in_a_tuple_slot_runs_correctly_beside_a_list: the compiler raised RuntimeError:
         parameter 'xs' of 'each' is passed a container at one call site and a str or number at another

## Likely causes (verify each; do not trust this list)

1. The first two are probably from the stage-7 work in `cpp_core.py` (`doc/GIR.md` section 6, T1-T6).
   The memo checker treats any `x.body = ...` write as an AST mutation. Stage 7's lambda / `Ex` shapes
   may have a `body` field. If so, the checker needs to tell an AST node from an IR shape (by class,
   not by field name). If the writes really are to AST nodes, call `_walk_ast_invalidate` there. The
   kwargs-gap test expects a lowering the stage-7 rewrite no longer emits in that form. Read the
   test's assertion and the generated `.cpp`, and decide whether the test is stale (the C++ is
   byte-identical by `c_oracle`) or the lowering was lost.
2. The two -11 crashes and the refusal look like the mixed-iterated-parameter work (commits
   `4e2efdfee`, `89c41e7de`, 2026-11-22). Bisect with
   `python3 -c "import test_gimple as T; T.<test function>()"` if a test can run alone, or with the
   whole file otherwise (about 30 min a step).

## Done when

All five pass, `python3 test_gimple.py` prints `0 failed`, and this doc is deleted in the same commit.
