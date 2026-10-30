# Gate job `gimplerunner` is red: gimple runner: compiled programs disagree with expected output

## Status

PARTIAL (2026-10-29, branch work/fix-gate-gimplerunner; also see master note). Reproduced alone (not load): `python3 test_gimple_runner.py` gives `477 passed, 4 failed` on the pre-fix tree. The four failures are the cases in `bugs/CODEGEN_mixed_kind_struct_and_list_reads_red_on_head.md`. Three are fixed in this round; the fourth (`gimple_ctor_param_polymorphic_slot_reads_receiver`) is the method-receiver bug in `bugs/CODEGEN_unresolved_method_receiver_returns_its_own_pointer.md`, which is owned by another worker. Previously (HEAD, pre-merge) `mojoc` was also red on master due to the imported-function trailing-default drop (`bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), fixed on `work/bug-codegen-imported-function-default-ar`; that reference is retained for gate tracking. The `gimplerunner` job stays red until the receiver bug lands.

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
