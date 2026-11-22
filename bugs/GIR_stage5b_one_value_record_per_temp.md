# GIR stage 5b (final): one value record per temp (Int / Erased / DynWord / Box)

Plan source: `doc/GIR.md`, Stage 5b. Steps 1-3 are landed (`WordFacts` in
`mojo/middle/valueinfo.py` owns the six dynamic-word sets; readers and writers go through
`gen._words` and the `gen._word_*` wrappers).

## Still open

Step 4 of the plan: change the storage to ONE record per temp whose kind is one of
`Int / Erased(T) / DynWord / Box`. This is the only step allowed to change generated C.

- The six sets are carried across copies by `carry_value_info` (`emit_infra.py`) ONLY partially: the
  dynamic-word sets are NOT carried yet. Carrying them measured about 1,200 extra box/repr calls, so
  each needs its own look.
- Land it alone, with its own diff review.

## Acceptance

- Generated C changes only where the new kind says it should; review the diff per function on
  `tools/pydiff_corpus` (hash `compile_to_gimple_with_cpp` before and after).
- `test_gimple.py` passes, `make bootstrap` gets past stage2 dumps (blocked
  upstream; the stage-1/2 gate docs under `bugs/` are the switches, and the
  per-file module-alias attribute shapes still open are in
  `bugs/CODEGEN_module_alias_attr_per_file_remaining_shapes.md`).
