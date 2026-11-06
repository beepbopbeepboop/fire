# plan/step-08a: name `BLR` in `_unmodelled_instruction` (the emitted indirect call has no step and no name)
**Status: DONE 2026-11-06 (measured).** `_unmodelled_instruction` names BLR (`arm64_proof_gen.py:8512`); `test_blr_is_named_not_unnamed` and the sp-encodings test pass (2 passed).
Class: easy      Size: S      Depends: none      Blocks: 08c
Source: `bugs/FORMAL_arm64_instruction_coverage.md` (`blr` mapping bug, `br` row).

## Current state (measured; verified 2026-11-05)
- `BLR X16` IS emitted: `formal/arm64_codegen.py:12360` `self.asm.emit(encode_blr_xn(16))` in the `through_value` arm of a call (lines ~11793-11806 decide `through_value`: a call whose callee is a function VALUE).
- `arm64_step` has NO BLR arm and `_STEP_CONDS` no row: `python3 -c "import formal.arm64_proof_gen as G; print(G._step_branch_index(0xd63f0200))"` -> `None` (0xd63f0200 = `blr x16`, assembled 2026-11-05 as `0xd63f0000 | 16<<5`).
- `_unmodelled_instruction(word)` (formal/arm64_proof_gen.py:8076) names STUR/LDUR and the extended-register ADD/SUB class and returns `None` for anything else; the caller (line ~8183) then prints "an instruction (0x...)  ... It is not one this path names". So a function-value call reaches the reader as an unnamed word.
- By contrast `BR` IS modelled (`arm64_step` arm `0xD61F0000`, `_STEP_CONDS` row 34, `work_step_br`, `_step_rhs` line 4601), and no CFG code special-cases index 34 (the terminator tuples at lines ~5792, 5811, 6277, 11512 are `(14, 15, 16, 17, 51, 52, 53)`): a modelled BR would be a fall-through in the walker. It never occurs in proof scope (only the linker stub emits it).

## Decisions already made
- BLR gets **no model row now** (design reason in step-08c: a row makes the walker treat it as a straight-line instruction, whose successor pc is the register's value, not pc+4). It gets a NAME and a true reason.
- Name: `"BLR"`; word test `(word & 0xfffffc1f) == 0xd63f0000`. Reason text (must contain the word `indirect` and `x{n}`): "a call through a REGISTER: the callee is a run-time value (a function used as a value), so the CFG walk has no successor to follow and the block's runs certificate cannot name the callee's entry; `arm64_step` has no BLR arm for the same reason. Emitted by the `through_value` arm of a call in `formal/arm64_codegen.py`".

## Work order
1. `formal/arm64_proof_gen.py::_unmodelled_instruction`: add the BLR case before the `top = word & 0xffc00000` line, returning `("BLR", why)` with `n = (word >> 5) & 0x1f` in the text. Update the docstring list ("The ones this emitter is measured to produce").
2. `test_formal_call_proof_gen.py`, class `TestRegister31` neighbourhood (the method at line 1684 is the template): `test_blr_is_named_not_unnamed`: `word = int.from_bytes(A.encode_blr_xn(16), "little")`; assert `G._step_branch_index(word) is None`, `G._unmodelled_instruction(word)[0] == "BLR"`, `"indirect" in why`, `"x16" in why`.
3. Do not touch `lib/`.

## Do NOT
- Do not add a `_STEP_CONDS` row or a Lean arm for BLR here (see 08c).
- Do not name `BR` as unmodelled (it is modelled).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 -m pytest -q test_formal_call_proof_gen.py -k "blr or sp_encodings"
```

## Done when
- [ ] the new test passes and `test_the_sp_encodings_are_named_rather_than_left_unnamed` still passes
- [ ] `python3 -c` prints `('BLR', ...)` for `0xd63f0200`

## If stuck
If `_unmodelled_instruction`'s caller never reaches it for a function-value program (the refusal comes from elsewhere), write the program, the first 10 lines of the refusal, and the file:line that raised it into "Status" and stop.
