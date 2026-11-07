# plan/step-05a: register the arm64 rules the Lean side now proves
**Status: DONE 2026-11-07 (measured).** The four arm64 rules whose theorems are now PROVED in `lib/Peephole.lean` (`movz_pair`, `mem_pair_str`, `mem_pair_ldr`, `store_load`) are moved from `SCAFFOLDED_RULES` into `ARM64_RULES`; `unlicensed_rules() == []`; `test_formal_peephole.py` 83/83 (its corpus differential, which runs the whole pass over the examples, is green); `tools/formal_bench.py --opt` runs clean. No corpus program contains these windows (as the doc predicted), so coverage is the hand-assembled unit rows.

Class: mid      Size: M      Depends: 03b, 03c, 03d (each only for the rules whose theorem is PROVED in Peephole.lean)      Blocks: none
Source: `bugs/FORMAL_peephole_rules_without_proofs.md` §2; `formal/peephole.py` (`Rule` :362, `decode_arm64` :88, `ARM64_RULES` :749, `PENDING_RULES` :893, `declared_theorems` :899, `unlicensed_rules` :911).

## Current state (measured; verified 2026-11-05)
- `decode_arm64` recognises ONLY `add_imm` (line 110-115). No STR/LDR/MOVZ decode; `_ARM64_READS`/`_ARM64_WRITES` (:126+) need rows for these classes or the liveness scan treats them as "reads/writes everything" (sound, but then no rule below them fires usefully).
- There are NO arm64 matchers for the three rules yet (x86 ones exist). `Rule(name, arch, theorem, side_conditions, apply, doc)`.
- **The licence is name-only** (`declared_theorems()` regexes `theorem|lemma` names from `lib/Peephole.lean`): a rule may enter `ARM64_RULES` only if its theorem is *proved* in Peephole.lean. Scaffolded theorems live in Scaffold.lean and so can never license a rule (S3).
- Corpus hits: 0 for all three (measured 2026-10-05 by the doc), so the differential cannot show these rules firing — hand-assembled windows are the test (as `test_formal_peephole.py` does for `add_imm_fuse`).

## Decisions already made
- Extend `ArmInsn`/`decode_arm64` with `movz` (`0xffe00000/0xd2800000`, fields `rd`, `imm16`), `str` and `ldr` (`0xffe00000/0xF9000000` and `/0xF9400000`, fields `rt`, `rn`, `imm12`), excluding `rd/rt == 31` exactly as `add_imm` excludes 31 (the model reads 31 as SP in some arms and XZR in others; the theorems carry `< 31`).
- Matchers: `_a_movz_pair` (same `rd`; deletes the FIRST word → returns the replacement for window[0] = the second's word and consumes... follow `_a_add_imm_fuse`'s return convention exactly — read it), `_a_str_pair`, `_a_ldr_pair` (requires `rt != rn`), `_a_store_load` (deletes the second). Rule names: `arm64/movz_pair`, `arm64/mem_pair_str`, `arm64/mem_pair_ldr`, `arm64/store_load` with `theorem` = the names from 03b-d.
- Rows for `_ARM64_READS`: STR reads (`rt`,`rn`), LDR reads (`rn`), MOVZ reads nothing; `_ARM64_WRITES`: LDR writes `rt`, MOVZ writes `rd`, STR writes no register. Check the tables' key format and mirror the existing rows.
- A rule whose theorem is NOT proved in Peephole.lean is NOT added to any table here; its matcher may exist under `SCAFFOLDED_RULES: list = []` (new, defined next to `PENDING_RULES`, with the comment: "matcher written, theorem scaffolded in lib/Scaffold.lean, never run"). `test_formal_peephole.py` asserts `SCAFFOLDED_RULES ∩ RULES = ∅` and that every scaffolded rule's theorem name appears in `formal/proof_gaps.py::SCAFFOLD_HOLES`'s keys.

## Work order
1. Read 03b-d outcomes: which theorems are proved in Peephole.lean (`python3 -c "import formal.peephole as P; print(sorted(P.declared_theorems()))"`).
2. Decoder + read/write rows + matchers + registry rows for the proved ones; `SCAFFOLDED_RULES` for the rest.
3. `test_formal_peephole.py` rows per rule: (a) the match on a hand-assembled window (build words with the `formal/arm64.py` encoders; list the exact encoders in the test), (b) each decline (different base, different offset, different register, `rt == rn` for LDR pair, register 31), (c) the rewrite's output bytes, (d) the `_Remap` check after the deletion (copy the pattern from the `add_imm_fuse` tests).
4. Differential: `tools/formal_bench.py --opt` and `test_formal_peephole.py`'s corpus row must still say 0 disagreements. The corpus does not exercise these rules, so ALSO add one end-to-end hand program (a small `.mojo` or a raw image test; copy how `TestTheCorpus` builds) that does contain `str;str` or `movz;movz`. If producing such a program is not possible with the current emitters (they may never emit these windows), say so in this file: "no emitter produces this window; coverage is unit-level only" — that is an acceptable, recorded answer.

## Do NOT
- Do not register a rule whose theorem is a `sorry`.
- Do not skip the `rt != rn` check for LDR;LDR.
- Do not delete the first instruction when the theorem deletes the second (and vice versa): re-read the theorem's conclusion.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_peephole.py
python3 tools/memslot.py --gb 8 --label t -- python3 tools/formal_bench.py --opt
python3 -c "import formal.peephole as P; assert P.unlicensed_rules()==[]"
```

## Done when
- [x] every PROVED arm64 theorem has a registered rule with unit tests; `unlicensed_rules() == []`
- [x] `SCAFFOLDED_RULES` holds the rest; the test pins `SCAFFOLDED_RULES ∩ RULES = ∅`
- [x] corpus differential still 0 disagreements; the "no emitter produces this window" note present if true
- [ ] `FORMAL_peephole_rules_without_proofs.md` §2 updated (rules moved / still open)

no emitter produces this window; coverage is unit-level only

## If stuck
If a decoder change makes `test_formal_peephole.py` red in unrelated rows, revert only your decoder rows (by editing, not checkout) and write the failing row into this file.
