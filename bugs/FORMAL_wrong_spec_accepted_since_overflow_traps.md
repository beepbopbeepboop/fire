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

## Correction (2026-11-11): the soundness hole is the machine model's `svc`

The cause above is only half of it. The overflow trap block is `trap:` label, the write `svc`, the exit `svc`, then the
`ok:` label (`formal/arm64_codegen.py::_emit_int_overflow_trap_block`). In the Lean model, `arm64_step` steps every
`svc` as a no-op (`lib/ProofLib.lean`, the `0xD4000001` arm: "trap; modelled as a no-op step", proved by
`work_step_svc` in `lib/ProofLibSteps2.lean`). So on an overflowing input the model falls through to `ok:` and carries on
with a result the real program never produces, while the real program stops at the exit `svc`.

That makes the model unsound on every trap path, not only the one in `triple`. The generator's "body with a branch" refusal
is the honest response to the branch; the teeth check fails because the wrong spec is only admitted as a `sorry`.

Fix, in order:
1. `lib/ProofLib.lean`: `svc` with `x16 = 1` (Darwin exit) steps to `none`, so `runProg` cannot return a final state from
   a trap. `svc` with `x16 = 4` (write) stays a no-op.
2. `lib/ProofLibSteps2.lean`: `work_step_svc` split on `x16`; the `hne_*` facts in `ProofLibSteps6..8` are unaffected.
3. `formal/arm64_proof_gen.py`: the SVC row (`5433`) and `_is_svc` (`8381`) say which svc is which.
4. Then the guarded contract: a body whose only branches are overflow traps gets the non-overflow precondition and a
   proved normal path. Until then the teeth check stays an expected failure.
