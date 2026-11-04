# Plan: Dispatched for-loop shared var (CODEGEN_dispatched_for_loop...)

Source bug: bugs/hard/CODEGEN_dispatched_for_loop_shares_one_var_between_dict_and_list_arms.md

## Decomposition

Step 1 — Decide representation (int64_t vs runtime query)
  Owner decision needed; document choice.

Step 2 — Implement chosen representation
  Files: mojo/backend_gimple/emit_loops.py (_gen_for_iter, _fl_ctype)

Step 3 — Update test_reg_dispatched_for_loop.py to pass.
