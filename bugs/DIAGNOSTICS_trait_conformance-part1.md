# DIAGNOSTICS_trait_conformance part 1: pin canonical defaulted-method application spelling

## Goal
When a defaulted trait method makes a conforming struct's inherited signature
unformable because it returns a partially-applied type application (e.g.
`Map[mapper]` where `mapper` is the trait method's own bracket parameter but the
struct declares that value parameter as `mapFn`), the diagnostic must report the
application re-spelled with the conforming struct's own bracket-parameter name.

Canonical case (from Modular's `defaulted_trait_method_bad_conformance.mojo`):
- trait default method: `def map[..., mapper: ...] -> Map[mapper]`
- struct declares: `struct Map[..., mapFn: ...]`
- expected diagnostic fragment: `'Map[mapFn]' does not implement all requirements for 'Strategy'`

## Acceptance
Compiling the canonical non-coincidental case (trait method parameter named
`mapper`, struct parameter named `mapFn`, default returns `Map[mapper]`) fails
with a diagnostic containing `'Map[mapFn]'` and `does not implement all requirements for 'Strategy'`.

## Done when
`python3 test_defaulted_trait_method_conformance_diagnostic.py` passes and
includes a case that exercises the `mapper` (trait) vs `mapFn` (struct) spelling.
