# plan/step-04a: `x86_64/mov_self_rev` — `mov r, r` spelled `48 8b c0`
**Status: DONE (verified by agent, work landed)**

Class: easy      Size: S      Depends: 00a, 01a, 01b      Blocks: 05b
Source: `bugs/FORMAL_peephole_rules_without_proofs.md` §3 table row `x86_64/mov_self_rev`.

## Current state (measured; verified 2026-11-05)
- Template: `lib/Peephole.lean:586` `peephole_x86_mov_self`, which instantiates `x86_step_mov_rm64_r64_reg_st` (**`lib/X86.lean:3016`**; the first draft said 2830) and uses `x86_set_reg_self` (Peephole.lean:563).
- The `0x8b` mirror needs the register-register LOAD-direction step lemma. Worker: `grep -n "theorem x86_step_mov_r64_rm64_reg\|0x8b" lib/X86.lean | head` — if no reg-reg `0x8b` lemma exists, add `x86_step_mov_r64_rm64_reg_st` in `lib/Peephole.lean` (NOT X86.lean — S4) by copying the 0x89 lemma's proof (same `simp [...]` list with `h_b1 : code (m+1) = 0x8b`). In the `0x8b` form `reg` is the destination and `rm` the source.
- Not emitted today and `_x_mov_self`'s docstring says the decoder only sees `48 89 c0`: this rule has **zero corpus hits**, so it is scaffold with a witness, not a live gain.

## Decisions already made
- Theorem `peephole_x86_mov_self_rev`, same hypotheses/conclusion shape as `peephole_x86_mov_self` with `0x8b`; proved in Peephole.lean (it is the same proof). Fallback: Scaffold + ledger.
- Do NOT register a rule (step 05b records it as `SCAFFOLDED_RULES`/not-run unless the decoder emits the form; check `formal/x86_64_decode.py` for an `0x8b` reg-reg form first and write the answer into this file).

## Work order
1. Check/add the step lemma. 2. Prove the theorem by copying `peephole_x86_mov_self`. 3. Witness `example` with concrete `modrm = 0xc0`.

## Do NOT
Edit `lib/X86.lean`.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_peephole.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_proof_gaps.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_admitted.py
```
(update the `Peephole` pins from measurement)

## Done when
- [x] theorem declared (proved), witness elaborates, three commands pass
- [x] this file records whether the decoder can see the form

Decoder: `formal/x86_64_decode.py` decodes `REX.W 0x8b /r` reg-reg as form `mov_r64_rm64` (mod==3) — it CAN see the form. However the compiler/emitter does not produce it (only `48 89 c0` observed), so the peephole matcher `_x_mov_self` only matches the store direction form `mov_rm64_r64`. Rule not registered; recorded for step-05b as scaffolded/not-run.

## If stuck
Scaffold the theorem, ledger row `step-04a`.
