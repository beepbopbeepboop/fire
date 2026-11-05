# Plan: Dispatched for-loop shared var (CODEGEN_dispatched_for_loop...)

Source bug: bugs/hard/CODEGEN_dispatched_for_loop_shares_one_var_between_dict_and_list_arms.md

## Decomposition

Step 1 — Decide representation (int64_t vs runtime query)
  **Decision:** Runtime query via `mojo_list_get_kinds` / element-type inspection at runtime (option b). This asks the iterable what its element kinds are before declaring the shared loop variable, avoiding the dict-arm-vs-list-arm type clash. `int64_t` would fix int lists but silently produce pointer-decimal wrong values for string-keyed dicts.

Step 2 — Implement chosen representation  [DONE]
  Files: mojo/backend_gimple/emit_loops.py (_gen_for_iter, _fl_ctype)
  Shared loop var type in boxed dict/list/set dispatch is now int64_t with
  _dyn_word_locals/runtime kind handling, not the dict arm's char*.

Step 3 — Update test_reg_dispatched_for_loop.py to pass.
