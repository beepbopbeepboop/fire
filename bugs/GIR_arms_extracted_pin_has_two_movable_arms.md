# GIR: `test_gimple_arms_extracted.py` is red — two giant functions have a movable arm again

`python3 test_gimple_arms_extracted.py` pins the 2026-11-14/15 arm split
(`doc/GIR.md`, "Stage 6, arms of the giant functions") by requiring
`tools/extract_arm.py --list FILE PARENT 25` to print `0 lines can be moved`
for each of the eight giant lowering functions. On master (faabc1806, 2026-11-21) it
reports 6/8 and exits 1:

    FAIL: emit_exprs.py: _lower_IdentExpr still has 25 movable line(s)
    FAIL: emit_exprs.py: _lower_binary_tail still has 27 movable line(s)

Both arms are newly movable — `test_gimple.py` and `test_gimple_lint.py` pass, and
nothing in `emit_exprs.py`'s recent history (the stage-4 type-predicate codemods,
`1b94b71d4`) says the split was reopened on purpose.

## What the tool now offers

    $ python3 tools/extract_arm.py --list mojo/backend_gimple/emit_exprs.py _lower_IdentExpr 25
    1202: 25 lines  returns  extra inputs: name  if name in gen.BUILTIN_VALUE_MAP and name not in gen.var_types and (not b
    25 lines can be moved

    $ python3 tools/extract_arm.py --list mojo/backend_gimple/emit_exprs.py _lower_binary_tail 25
    4782: 27 lines  falls through  extra inputs: _tagged  if op in ('==', '!=', 'is', 'is not') and _is_none_literal(left_node) !=
    27 lines can be moved

The other 39 lines in `_lower_binary_tail`'s `--list` output are the tool's own
refusals (`NO (...)`), which are the accepted end state.

## Expected

`6/8` is the state `test_gimple_arms_extracted.py` exists to catch: an arm is in
the parent that the tool can move.

## Next step

Do what the original arms round did, for two arms:

    python3 tools/extract_arm.py mojo/backend_gimple/emit_exprs.py _lower_IdentExpr 1202 \
        _lie_builtin_value_map_fastpath "..." name:<type from the dump>
    python3 tools/extract_arm.py mojo/backend_gimple/emit_exprs.py _lower_binary_tail 4782 \
        _lbt_none_compare "..." _tagged:<type from the dump>

(load the dumps with `python3 fire.py --dump mojo/backend_gimple/emit_exprs.py` first:
the new parameter must get the C type the local has in `_lower_IdentExpr` /
`_lower_binary_tail`'s declarations — `char *` is `:str`, `_Bool` is `:bool`,
`int64_t` is no annotation), then `python3 test_gimple_arms_extracted.py` (8/8),
`python3 tools/c_oracle.py check --base <before> -j 4` (identical C) and
`python3 test_gimple.py`. The test is not registered in `tools/suite.py`, so a
gate does not run it; it is red silently until something does.
