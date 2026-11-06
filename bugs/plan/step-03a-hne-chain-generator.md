# plan/step-03a: a generator for the `hne_` negation chain of an `arm64_step` arm lemma
**Status: DONE 2026-11-05 (verified).** `tools/lean_hne_chain.py` + `test_lean_hne_chain.py` (3 tests) pass; its output was used to regenerate the `work_step_*` theorems in step 00f/00g, where its chains elaborated (see those steps).

Class: mid      Size: S      Depends: none      Blocks: 03b, 03c, 03d
Source: `bugs/FORMAL_peephole_rules_without_proofs.md` §2 ("26 negations"); template `lib/Peephole.lean:166` `arm64_step_add_imm64`.

## Current state (measured; verified 2026-11-05)
- A per-arm step lemma for a peephole rule is a hand-copied block of `have hne_X : ¬ (...) := by intro t; bv_decide` lines — ONE PER EARLIER ARM of the `if`-chain in `lib/ProofLib.lean:2097` `arm64_step` — followed by `unfold arm64_step; rw [hpc, hread]; rw [if_neg hne_ret, if_neg hne_orr, …, if_pos h]`. See `arm64_step_add_imm64` (Peephole.lean:166-206).
- This is **not** `work_step_*` (ProofLib has 13 of those and they are untouched by this plan): no edit to ProofLib is needed to add a rule's step lemma. (The first draft said otherwise; it was wrong.)
- Target arms: `MOVZ` `0xd2800000` (arm at ProofLib:2476), `STR` `0xF9000000` (:2541), `LDR` `0xF9400000` (:2392). Arm order is the textual order in the chain; STR is later than LDR textually.
- The first arm is `insn = 0xd65f03c0` (RET, an equality not a mask); the rest are `(insn &&& MASK) = VAL`, but at least some arms are compound — read the chain before writing the parser.

## Decisions already made
- Write `tools/lean_hne_chain.py` (pure Python, no Lean): parses `arm64_step`'s `if/else if` chain out of `lib/ProofLib.lean` (between `def arm64_step` and `def arm64_steps`), and given a target `(MASK, VALUE)` prints (a) the `have hne_<n> : ¬ ((w &&& MASK) = VAL) := by intro t; bv_decide` lines for every arm BEFORE the target and (b) the matching `rw [if_neg hne_…, …, if_pos h]` line. Variable named `w` as in the template.
- Arms the parser cannot read (compound conditions) are printed as `-- UNPARSED arm at line N: <text>` and make the tool exit 2: the worker writes those by hand. Never skip silently.
- The `ret` arm uses the template's special form (`intro t; rw [t] at h; exact absurd h (by decide)`); emit that when the first arm is an equality, but only valid if the target class excludes the RET word — print a note.
- Hypothesis `h` for the target is `(w &&& MASK) = VAL`, same as the template.

## Work order
1. Create `tools/lean_hne_chain.py` with `--mask 0xffe00000 --value 0xd2800000` and `--list` (prints every arm with its line number and parsed condition).
2. Create `test_lean_hne_chain.py`: assert (a) for the ADD-imm arm (`0xff800000`/`0x91000000`) the output's `hne_` conditions equal, in order, the ones in `lib/Peephole.lean:166-206` (parse those out of the file, so the test tracks the template); (b) `--list` count equals the number of `else if` + 1 in the chain; (c) exit code 2 when an arm is unparsed (use a synthetic source string through the library function, not the real file).
3. Run `--list`, and paste the arm count and the three target arm indices into this file's "Measured" section below.

## Do NOT
- Do not edit `lib/ProofLib.lean`.
- Do not "fix" arms that look redundant; the chain is the model.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_lean_hne_chain.py
python3 tools/lean_hne_chain.py --list | tail -5
```

## Done when
- [x] tool + test exist; test passes
- [x] "Measured" section lists the arm count and the index of MOVZ, LDR, STR
- [x] registered in a `tools/suite.py` bucket (see 01b step 5 for how)

## If stuck
If the chain has many compound arms, make the tool print them verbatim as UNPARSED and still emit the rest; the worker of 03b-d handles those by hand.

## Measured
- arm count: 81 (80 `else if` at chain level + 1 initial `if`)
- MOVZ `0xd2800000` (line ~2476): index 27
- LDR `0xF9400000` (line ~2392): index 21
- STR `0xF9000000` (line ~2541): index 34
