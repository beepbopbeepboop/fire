# FORMAL: the call-path proof tests are red because `_call_go` demands `scope.structs_by_name`

Gate job `formal-call-proofgen` (`tools/suite.py`, `python3 test_formal_call_proof_gen.py`;
`deps=['preflight', 'prooflib']`, no `expect=` marker). Class: easy-to-mid — the root cause is
one un-defended attribute read, but the fix must not change what the generator emits.

## Symptom (measured 2026-11-17, three independent trees)

`python3 -m pytest test_formal_call_proof_gen.py -q`, wrapped in
`python3 tools/memslot.py --gb 8 --label <x> --`, in:

1. branch `work/bug-land-formal-arm64-instruction-covera-9` (tip ac9a703e4),
2. a clean checkout of that branch's merge-base `161c0b7c2`,
3. the materialised merge of that branch into current master
   (`git merge-tree --write-tree`; the tree object, read-tree'd and
   checkout-index'd — identical contents to the merge the integrator will make),

all give the SAME result: **22 failed, 272 passed, 14 skipped, 792 subtests passed**.
The failing set is identical across the three trees (20 test names; two of the
TestTheDivideByZeroGuard rows fail as subtests on both backends), so no commit on
that branch contributes a failure. The deterministic failure is

    AttributeError: '_Scope' object has no attribute 'structs_by_name'
    formal/arm64_proof_gen.py:942

with the caret on

    ... sym in (getattr(scope,'structs_by_name') or {}) and ...

inside `_call_go`'s "rough check" line (master's numbering; the base-era tree
carries the same line). A two-argument `getattr` with no default raises exactly
when the `_Scope` object carries no `structs_by_name` attribute; every other
read of that attribute in the file defends (`getattr(scope, 'structs_by_name',
None)`, `hasattr`, `scope.get(...)` on the dict base class,
`scope.__dict__.get(...)`), which is how the generator intends the attribute to
be optional.

Second, downstream class: the `TestCallProofs` rows then fail with
`TypeError: expected str, bytes or os.PathLike object, not NoneType` at
`open(self.proofs["same_image_leaf"])` — the setUpClass generation that is
supposed to produce those proof files died on the AttributeError above, so the
path slot is `None`. The TypeErrors are the same red, not a second bug.

## What it breaks

22 test results across `TestGeneratorSource`,
`TestTheDivideByZeroGuardIsEmittedOnlyWhenItCanFire`, `TestCallProofs`,
`TestAstBridgeCallLimit`, `TestAPlaceholderModelClaimsNothing` and
`TestCfgLeafCensus` — the whole call-path half of the arm64 proof generator
(a call must not raise, the model must be the model of the call, the AST-bridge
limit, the placeholder model).

## Why this doc exists now

The red predates the branch that filed it: the arm64 instruction-coverage
parent doc (retired on master 2026-11-17 in `9b432aea7` with the three part
docs) recorded in its 2026-11-14 Status entry that the file's "21 failures /
6 errors reproduce with `643fdf026` stashed (a pre-existing `_Scope` object
has no attribute `structs_by_name` in `_call_go`)". The retirement closed the
parent on the strength of the part tests alone, and no live doc carried the
whole-file red forward, so `formal-call-proofgen` is now an unmarked red.

## Done when

`python3 tools/memslot.py --gb 8 --label fcpp -- python3 test_formal_call_proof_gen.py`
exits 0 (22 failures gone; the 14 skips are the lean-toolchain skips and stay).
If the attribute read is fixed and failures remain, this doc records the
remainder instead — one doc per bug.

## Next step

In `formal/arm64_proof_gen.py`, in `_call_go`'s rough-check line (the `942`
above), read the attribute the way the rest of the file does —
`getattr(scope, 'structs_by_name', None)` in place of the two-argument
`getattr(scope,'structs_by_name')` — so a scope without the attribute falls
through the check instead of raising. Grep for the same two-argument spelling
before editing; fix every un-defended occurrence the same way (the fix must be
behaviour-identical for scopes that DO carry the attribute). Re-run the file
under memslot as in Done when; the 22 must drop and nothing new may appear —
if any of the 22 keeps failing after the AttributeError is gone, that one is a
separate bug and gets its own doc.
