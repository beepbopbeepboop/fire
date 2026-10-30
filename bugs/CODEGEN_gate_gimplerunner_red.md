# Gate job `gimplerunner` is red: gimple runner: compiled programs disagree with expected output

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (the imported-function trailing-default drop, which made `mojoc`'s `compile_to_gimple` call three-argument; fixed on `work/bug-codegen-imported-function-default-ar`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
PASS  user_struct_named_parser_survives_a_re_export_and_a_base
PASS  gimple_id_is_an_integer
PASS  gimple_erase_slot_holding_a_string
PASS  gimple_star_spread_of_string_beside_own_slot
PASS  user_struct_named_parser_emits_its_own_layout_and_qualifier
Results: 467 passed, 5 failed
```

## What to check first

see excerpt; gimplerunner ran 981 s, rerun alone.

## Next step

1. Run `python3 tools/suite.py gimplerunner` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
