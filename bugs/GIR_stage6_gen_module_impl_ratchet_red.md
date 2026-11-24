# GIR stage 6: gen_module_impl grew 8674 -> 8710 lines; test_gimple_module_passes.py is red

`python3 test_gimple_module_passes.py` on master (2026-11-23):
`FAIL: gen_module_impl is 8710 lines, over the 8674-line ratchet: extract the new pass with
tools/extract_arm.py --phase instead of inlining it`.

The growth after the ratchet was set (`8eba91535`):
- `4e2efdfee` (+33): the separately compiled definer's unannotated iterated parameter fix. This is
  the one to extract.
- `2adea3531` (+1) and `89c41e7de` (+2).
- 2026-11-23: the stage 5c call-site pass added 14 more; it was moved into `_gmp_collect_param_value_obs` at merge, leaving a one-line call (8712 lines).

## What to do

1. Find the block that `4e2efdfee` added inside `gen_module_impl` (`mojo/backend_gimple/module_gen.py`).
2. `python3 tools/extract_arm.py --list-phases mojo/backend_gimple/module_gen.py gen_module_impl`
   should list it. Move it with `--phase` into a `_gmp_*` function, as the other passes are.
3. If the tool refuses (the block binds a name read later, or calls a nested function), do not force
   it. Report the refusal reason and set `PARENT_LINES` in `test_gimple_module_passes.py` to the
   measured count, with a comment naming the three commits.
4. Add the new pass to the pinned rows the test checks, if it pins each pass by name.

## Checks

    python3 test_gimple_module_passes.py              # 0 failures
    python3 tools/c_oracle.py check --base <start sha> -j 4   # identical C

Delete this doc in the same commit.
