# FORMAL: a wrong spec is accepted by Lean since integer overflow traps went in

Found 2026-11-10 by the bisect of `test_formal_dylib.py`'s "a wrong spec is rejected, not believed".

## Symptom

The check builds `def triple(n): return n * 3`, generates the dylib proof with the WRONG spec `n * 5`, and asks
Lean to check it. It must be rejected (a counterexample). On `a2135f390` and later, Lean accepts it. Its proof text
has `sorry`s.

## Measured

- Good: `096dd6e55`. The generated proof has no `sorry`. Lean: `counterexample: n = 18446744073709551615`. Image: 60 bytes.
- Bad: `a2135f390` and master. The generated proof has the export's contract as `dylib_export_0_triple_spec ... := by sorry`
  ("a body with a branch is not one function of one state"). Lean accepts. Image: 513 bytes.
- In the bad image, `triple` contains conditional branches to `triple_ovf1_t` / `triple_ovf1_k` (offsets 0x40, 0x78),
  the integer overflow trap around the multiply.

## Cause

`20d8bdba1` ("formal: refuse every integer overflow the build can decide, on both backends", 2026-10-05) makes the
multiply in `triple` a checked operation with a branch to a trap. The export is therefore not straight-line.
`formal/arm64_proof_gen.py` only builds the contract for a straight-line body. A branchy body gets the spec as an
admitted `sorry`, so there is nothing for Lean to check, and the teeth check fails.

Ruled out: the float-repr helper (`a2135f390`'s other change). `triple` never prints a float, so no helper is in the
image. A change to the last export's extent for the helper did not help, and was reverted (see the branch history).

## Next step

Teach the export's control-flow walk to treat a branch whose target is an overflow trap (a `*_ovf*_t` label that never
returns normally) as an exit that cannot be taken on a non-overflowing input, so the normal path is straight-line and the
contract is proved again. Then the wrong multiplier must be rejected with a counterexample, and the right one accepted.
Also: an exported contract that is an admitted `sorry` must not pass the teeth check. Delete this doc in the commit that fixes it.
