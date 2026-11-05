# plan/step-05b: register the x86-64 rules, and fix three latent soundness holes in their matchers
Class: mid      Size: M      Depends: 04a, 04b, 04c, 04d (each only for rules whose theorem is PROVED in Peephole.lean)      Blocks: none
Source: `bugs/FORMAL_peephole_rules_without_proofs.md` §3; `formal/peephole.py` (`_x_mem_pair` ~765, `_x_store_load` ~789, `_x_imm_zero` ~835, `X86_RULES` ~867); `formal/x86_64_decode.py` (`_modrm_fields` :108-154, dataclass :86).

## Current state (measured; verified 2026-11-05)
The matchers exist but are deliberately outside `X86_RULES`. Reading them against the decoder shows THREE soundness holes that the missing theorems were hiding:
1. **SIB index ignored.** For `rm == 4` the decoder sets `mem_base = base` and discards the index and scale (`x86_64_decode.py:139-142`). `_x_mem_pair` compares `(mem_base, mem_disp, rm)`, so `mov [rax+rcx*8], r ; mov [rax+rdx*8], r` compares equal and the second store would be deleted — a wrong answer.
2. **RIP-relative.** `mem_base = None` for `rm == 5, mod == 0` (:144); `_x_mem_pair`/`_x_store_load` accept `None == None`. The disp is relative to each instruction's own end, so equal disps are DIFFERENT addresses.
3. **Load pair with `reg == base`** (and, with SIB, `reg == index`): the first load clobbers the address register; the second load reads elsewhere. No check exists.
Also: `mod == 3` register-register `mov_rm64_r64` pairs satisfy `_x_mem_pair`'s first branch (`mem_base` None) — harmless but outside any memory theorem; and `mov_rm64_imm32` pairs have no step lemma (04c).

## Decisions already made
- Decoder: add `has_sib: bool = False` to the decoded-instruction dataclass (`x86_64_decode.py:86`), set True when `rm == 4 and mod != 3`; add a decoder unit test (`test_x86_64_decode.py`).
- Matchers (all three): decline when `mod == 3`, `mem_base is None`, or `has_sib`; restrict to `mod == 1` (disp8) because only the disp8 theorems (04b/04c) exist; `_x_mem_pair`'s load branch additionally requires `d.reg != d.mem_base`; drop the `mov_rm64_imm32` branch (no theorem) — leave a comment pointing at 04c.
- Registry rows (only when the theorem is proved in Peephole.lean): `x86_64/store_load` ← `peephole_x86_store_load_disp8`; `x86_64/mem_pair_store` ← `peephole_x86_store_pair_disp8`; `x86_64/mem_pair_load` ← `peephole_x86_load_pair_disp8`; `x86_64/mov_self_rev` only if the decoder can produce the form (see 04a) else `SCAFFOLDED_RULES`; `x86_64/imm_zero` → `SCAFFOLDED_RULES` (04d: flags). `SCAFFOLDED_RULES` is introduced in 05a; if 05a has not landed, introduce it here with the same comment and test.
- Each matcher's docstring gets the three holes above as "declines because" lines.

## Work order
1. Decoder field + test. 2. Matcher fixes. 3. Tests in `test_formal_peephole.py` per rule: the match (disp8 stack form from the real encoder), and one decline test per hole (SIB with different index; RIP-relative pair with equal disp; `mov rax,[rax+8]` twice). The decline tests ARE the regression for the soundness bugs: write them first and watch them fail against the old matchers (record the failure in this file). 4. Registry rows for proved theorems. 5. Corpus differential: `python3 tools/formal_bench.py --opt` + `test_formal_peephole.py`'s x86 corpus row — 0 of N disagree AND report whether the pass fired; if no corpus program contains the windows, record "unit-level coverage only".

## Do NOT
- Do not enable `imm_zero`. Do not register a rule over a scaffolded theorem. Do not widen to `mod 0/2` without the matching theorem.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_peephole.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_x86_64_decode.py
python3 tools/memslot.py --gb 8 --label t -- python3 tools/formal_bench.py --opt
python3 -c "import formal.peephole as P; assert P.unlicensed_rules()==[]"
```

## Done when
- [ ] the three decline tests exist, failed before the fix, pass after
- [ ] every PROVED x86 theorem has a registered rule; `unlicensed_rules() == []`; the rest are in `SCAFFOLDED_RULES`
- [ ] corpus differential unchanged (0 disagreements) and the fired/not-fired fact is recorded
- [ ] `FORMAL_peephole_rules_without_proofs.md` §3 updated; if every §2/§3 rule is now registered or scaffolded with a recorded reason, rewrite the doc's Status accordingly (it stays open while any theorem is a hole)

## If stuck
If the decoder change breaks encoder round-trip tests, write the failing test into this file and stop.
