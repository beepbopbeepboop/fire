# GIR stage 4 (tail): the remaining type-string tests become `TypeLattice` / `Type` calls

Plan source: `doc/GIR.md`, Stage 4 (`var_types` holds `Type`, not strings).

## Measured now (`python3 test_type_string_ratchet.py --counts`)

- `in (.., 'int64_t', ..)` is 317 (baseline raised 313 -> 317 on the 2026-11-21 upstream merge; the
  four extra tests are upstream's and need rewriting).
- The other patterns are at their post-codemod baselines (`endswith(' *')` 37, `== 'int64_t'` 64,
  `== 'char *'` 75, `== '_Bool'` 11, `== 'double'` 10, `== 'MojoList *'` 32).

## Next step

1. Add `TypeLattice.is_int_or_word(t)` for the `in ('int', 'int64_t')` membership tests, and
   rewrite the `in (..'int64_t'..)` tuples with it. Check each one by hand: some list other types.
2. Lower the `in (.., 'int64_t', ..)` baseline back to the count it reaches.
3. Then the ratchet can only shrink again.

## Acceptance

- `test_type_string_ratchet.py` passes at a lower baseline.
- Generated C byte-identical on `tools/pydiff_corpus` (hash before and after).
