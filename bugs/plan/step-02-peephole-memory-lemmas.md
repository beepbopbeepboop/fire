# plan/step-02: the two memory lemmas the peephole store rules actually lack
**Status: DONE 2026-11-06 (measured).** The 2026-11-05 first-wave stamp was FALSE: none of the three lemmas existed anywhere in `lib/` or its history. Written now in `lib/Peephole.lean`: `mem_write_u64_idem`, `mem_write_bytes_idem` (+ `mem_write_bytes8_idem`), `arm64_set_reg_self`, via an inside/outside-the-window split (`simp` does not finish 8 nested `if`s). `lib/` builds clean (`ensure_library`, 2026-11-06); `test_formal_axioms.py` 2/2.

Class: mid      Size: S      Depends: 00a, 01a, 01b      Blocks: 03c, 03d, 04b, 04c
Source: `bugs/FORMAL_peephole_rules_without_proofs.md` §2 ("The recipe that works"), §3.

## Current state (measured; verified 2026-11-05)
The doc's claim "nothing that says `mem_read_u64 (mem_write_u64 m a v) a = v`" is **stale**:
- arm64 read-after-write EXISTS: `lib/ProofLib.lean:297` `@[simp] theorem mem_read_after_write_u64 (mem addr val) : mem_read_u64 (mem_write_u64 mem addr val) addr = val`. Also `_ne` (434), `mem_read_two_writes*` (459-499).
- x86 read-after-write EXISTS: `lib/X86.lean:3694` `mem_read_bytes_write_same (m a v)` (width-8 form — read its exact statement first), plus `_above/_below` (2155/2166).
- Definitions: arm64 `mem_write_u64`/`mem_read_u64` (ProofLib:86/97, 8-byte little-endian, `Nat → UInt8` memory); x86 `mem_write_bytes`/`mem_read_bytes` (X86:298/304, recursion on width).
What is genuinely MISSING (worker: confirm each with `grep -n 'idem\|write_same\|write_write' lib/ProofLib.lean lib/X86.lean` first):
1. **Write idempotence**, both models — what a *duplicate store* rule needs: `mem_write_u64 (mem_write_u64 m a v) a v = mem_write_u64 m a v` and the width-8 `mem_write_bytes` analogue.
2. **Load-set-reg identity**: after `r := mem[a]` where `mem[a]` was just stored from `r`, the register file is unchanged. This is not a memory lemma; it is `arm64_set_reg k s (arm64_reg k s) = s` for `k < 31`. Check `lib/Peephole.lean` ~110-135 (`arm64_set_reg_*`) and `peephole_arm64_mov_self` (line 248) — the identity may already be inside mov_self's proof; if so extract it as a named lemma. (x86 equivalent exists: `x86_set_reg_self`, Peephole.lean:563.)

## Decisions already made
- **Where**: all NEW lemmas go in `lib/Peephole.lean` (it imports `ProofLib` and `X86`, nothing imports it, so editing it does not rebuild `ProofLib`/`X86` or invalidate any generated-proof verdict — Shared mechanics S4). Section title `/-! ## Memory lemmas the store rules need -/`, placed before `/-! ## The rules`.
- If a lemma will not prove inside this step, put the STATEMENT in `lib/Scaffold.lean` with `sorry` and a ledger row (kind `scaffold`, step `step-02`) instead — never leave a `sorry` in `Peephole.lean`.
- Proof sketch for (1) arm64: `funext i; simp only [mem_write_u64]; split_ifs <;> simp_all` (all 9 branches have equal RHS); if `simp_all` loops, `by_cases i = a` ladders. x86 width 8: unfold `mem_write_bytes` eight times (`simp [mem_write_bytes]`), then `funext i; split_ifs <;> simp_all`. Try `bv_decide` only for the bit parts.

## Work order
1. Grep-confirm the four statements above. Add `mem_write_u64_idem` and `mem_write_bytes8_idem` (names fixed) in the new Peephole section.
2. Add `arm64_set_reg_self (s) (k) (hk : k < 31) : arm64_set_reg k s (arm64_reg k s) = s` unless an identical lemma exists (then skip and cite it).
3. Above each lemma, a comment naming the rule window that consumes it: `mem_write_u64_idem` ← `arm64/mem_pair` (STR;STR) step 03d; `mem_write_bytes8_idem` ← `x86_64/mem_pair` step 04c; `arm64_set_reg_self` ← `arm64/store_load` and LDR;LDR in 03c/03d.
4. Build via the tests below.

## Do NOT
- Do not add a second memory semantics or restate `mem_read_after_write_u64`.
- Do not touch `lib/ProofLib.lean` or `lib/X86.lean`.
- Do not claim a lemma proved that is `sorry`-backed (it lives in Scaffold then).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_peephole.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_proof_gaps.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_admitted.py
```
`test_formal_admitted.py` pins the `Peephole` row (`(0,0,9,9)`, AXIOM_CLOSURE `(14,1,10,0,3,0)`): new lemmas change "asked" and maybe the `bv_decide` tally. Update those two pins **from the measured output** in this commit (S4).

## Done when
- [ ] the three lemmas exist (or the unprovable ones are in Scaffold with ledger rows)
- [ ] each has its consuming-rule comment
- [ ] the three commands pass, pins updated from measurement
- [ ] `FORMAL_peephole_rules_without_proofs.md` §2 gets a one-line correction: "read-after-write already exists (ProofLib:297, X86:3694); what was missing is write idempotence" with the date

## If stuck
If idempotence needs more than ~40 lines, ledger it in Scaffold with `sorry` and move on; steps 03/04 can still state their theorems against it.
