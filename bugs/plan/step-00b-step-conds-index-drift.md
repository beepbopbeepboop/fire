# plan/step-00b: `_STEP_CONDS` index drift — the STRB register-offset row sits in the middle of the table
Class: easy      Size: S      Depends: none      Blocks: 06b, 07a, 08a, 09a
Source: found 2026-11-05 while verifying steps 06-09; no `FORMAL_*.md` owns it. Introduced by commit `6fa9db2d2` (2026-11-03, "wire STRB regoff").

## Current state (measured; verified 2026-11-05)
- `formal/arm64_proof_gen.py:4204`: `(0xffe0fc00, 0x38206800),  # 70 STRB Wt, [Xn, Xm]` is **list position 64**, inside the run commented 62..65. Every later row therefore sits one position higher than its comment and than every hard-coded index in the file. Measured: `python3 -c "import formal.arm64_proof_gen as G; print(len(G._STEP_CONDS), G._step_branch_index(0x9a821020))"` -> `81 70` (CSEL), but `_step_rhs`, `_regs_written` (line ~5884 `(...,68, 69)`), `_WORK_STEP` and `test_formal_call_proof_gen.py:954` all say CSEL is 69.
- Red test today: `python3 -m pytest -q test_formal_call_proof_gen.py -k csel_is_modelled` -> `AssertionError: 70 != 69`. (Others in that file will be red for the same reason; list them with the same command without `-k`, it takes minutes — run it in the background.)
- The code expects STRB regoff to be index 70 (`formal/arm64_proof_gen.py` lines 4633, 4636, 4665, 4938, 4941, 4964 and `_WORK_STEP` line 5058), but index 70 is ALSO claimed by FCMP (`_WORK_STEP` line 5070, comment at 4283). Two instructions, one number.
- Table length is 81 (positions 0..80); the real last row (FCVTZS) is position 80, commented 79.

## Decisions already made
- Move the STRB-regoff row to the END of `_STEP_CONDS` (it becomes position **81**) and renumber STRB regoff from 70 to 81 everywhere. All other rows return to their commented positions (CSEL 69, SMULH 68, FCMP 70, FCVTZS 79). Reason: appending is the table's own rule ("a new instruction goes last", comment at ~4175); the row was inserted mid-table by mistake.
- `check_step_conds`/`audit_step_table` compare SETS and per-pair overlap order against `lib/ProofLib.lean`; moving the row to the end is safe iff no earlier row overlaps `0xffe0fc00/0x38206800` (none does: STRB-regoff has bit 21 set and bits 15:10 = 011010).

## Work order
1. Delete the line at 4204 and re-append it as the last row of `_STEP_CONDS` with comment `# 81 STRB Wt, [Xn, Xm] (register offset, LSL #0)`.
2. In `formal/arm64_proof_gen.py` change the STRB-regoff index 70 -> 81 at: `_step_rhs` (4633 group tuple, 4636 tuple, 4665), `_step_rhs_generic` (4938, 4941, 4964), `_regs_written` (grep `70` in the function; the tuple that lists the memory-store indices), `_WORK_STEP` row `(70, "work_step_strb_regoff", ...)` -> 81. Find all with `grep -n '\b70\b' formal/arm64_proof_gen.py`; every hit that means STRB-regoff changes, every hit that means FCMP (line 4283 comment, `_WORK_STEP` 5070) stays 70.
3. Verify the numbering matches the comments: `python3 - <<'E'` printing `G._step_branch_index(<encoder word>)` for CSEL (expect 69), SMULH (68), CMN (66), TST (67), FCMP `0x1e602000` (70), FCVTZS `0x9e780000` (79), STRB regoff `0x38206800` (81), LDUR `0xf8400000` (64), STUR (65); and `len(G._STEP_CONDS)` == 82.
4. Grep the other consumers of the hard-coded numbers and confirm they agree: `grep -rn "G._STEP_CONDS\[\|_step_branch_index(.*), [0-9]" test_*.py`.

## Do NOT
- Do not renumber any other row to "make room" or re-label comments to match positions; the code's numbers are the truth, the row was misplaced.
- Do not edit `lib/ProofLib.lean` (the model's chain order is irrelevant to the table order; `audit_step_table` checks that).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 -m pytest -q test_formal_call_proof_gen.py -x
python3 tools/memslot.py --gb 8 --label t -- python3 -m pytest -q test_formal_eval_eq_mojo_bridge.py -k step_branch
python3 -c "import formal.arm64_proof_gen as G; G.check_step_conds(); print(len(G._STEP_CONDS))"   # 82
```

## Done when
- [ ] the step-3 probe prints the commented numbers and `len == 82`
- [ ] `test_formal_call_proof_gen.py` has no failure caused by an index mismatch (any remaining red is listed in this file under "Remaining reds" with its first assertion line)
- [ ] `G.check_step_conds()` passes

## If stuck
If another row is also out of place (the probe disagrees for a row other than STRB regoff), list it under "Blocked" with its position and stop; do not guess a renumbering.
