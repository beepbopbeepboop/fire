# plan/step-08b: `br` is emitted (the Mach-O stub) — fix the audit's scope and the stale "uncalled" claims
**Status: DONE 2026-11-06 (measured).** The audit counts the linker stub, `EMITTED_ONLY_BY_STUB` is printed, `encode_br_xn` is no longer listed unwired; `test_arm64_encoders.py` 932/0.
Class: easy      Size: S      Depends: none      Blocks: none
Source: `bugs/FORMAL_arm64_instruction_coverage.md` ("`encode_br_xn` really is uncalled … a genuine 359-occurrence gap", §"Re-measured 2026-10-05").

## Current state (measured; verified 2026-11-05)
- `encode_br_xn` has a caller: `formal/macho_linker.py:840-846` `_stub_bytes` emits `adrp x16 / ldr x16,[x16,#off] / br x16` for every extern symbol stub, i.e. in every image that calls an extern. The doc's claim "nothing calls it" is false for the linker.
- `tools/formal_isa_census.py:104` `LEVER_ROOTS["arm64"] = ("formal/arm64_codegen.py", "formal/macho_linker.py")` ALREADY counts the linker as an emitter ("a form only it uses is still a form an image can contain"). `tools/arm64_insn_audit.py::lowering_files()` (line 218) returns only `arm64_codegen.py` and `arm64.py`; so the two tools disagree about whether `br` is emitted.
- Model/test status of `br` (all present): `arm64_step` arm `0xD61F0000` (`lib/ProofLib.lean:2613`), `_STEP_CONDS` row 34, `work_step_br`, `_step_rhs` (line 4601), AS case `test_arm64_encoders.py:461-462`, census `HARNESS_LIMITS["encode_br_xn"]` (a register target cannot be given to the fuzz harness). Nothing in the compiler's constructs needs an indirect JUMP in generated code (no jump tables, no computed goto, no tail call through a register); the 366 real `br` in the 200-binary corpus (re-measured 2026-11-05) are those.
- `test_arm64_encoders.py::test_a_reference_from_something_that_cannot_emit_is_not_a_caller` (line ~708) PINS `lowering_files()` to the basenames `{arm64_codegen.py, arm64.py}` and requires `ASSEMBLER_EMITTED["adrp"]` to exist. `adrp` is also called by the linker (`macho_linker.py:840`).

## Decisions already made
- `lowering_files()` gains `macho_linker.py` (the audit and the census must agree; the linker stub is in the image). Consequences accepted: `br` leaves the "encoders no lowering emits" list and `br` leaves the uncovered list (its 366 real occurrences are then reported as covered by an encoder; the stub is the only emitter and this is stated in the docstring so nobody reads it as "jump tables supported"); `encode_adrp` also becomes wired by name.
- `ASSEMBLER_EMITTED["adrp"]` is KEPT (the test requires it and it is still true that `Assembler.emit_adrp_add` emits ADRP+ADD as raw words for relocations) but its text is reworded: "the code generator emits ADRP+ADD as raw words …; `encode_adrp` itself is called only by the linker stub".
- A decline note for the real-binary `br` instructions: the audit prints a new line in the report header, `br: emitted only by the Mach-O stub (formal/macho_linker.py); no construct of the source language needs an indirect jump`. Implement as a one-entry dict `EMITTED_ONLY_BY_STUB = {"br": "..."}` printed like `ASSEMBLER_EMITTED`.

## Work order
1. `tools/arm64_insn_audit.py`: `lowering_files()` adds `os.path.join(os.path.dirname(path), "macho_linker.py")`; update its docstring (why the linker counts; the census agrees). Add `EMITTED_ONLY_BY_STUB` and print it in `main()` beside the `ASSEMBLER_EMITTED` block. Fix the module-docstring paragraph at ~"`BR` is NOT in this table — `encode_br_xn` really is uncalled" (line ~144) and the Measured paragraph.
2. `test_arm64_encoders.py` (~line 745): change the basename set to `("arm64_codegen.py", "arm64.py", "macho_linker.py")` and update the failure message; add a positive assertion that `encode_br_xn` is NOT in `audit.unwired_encoders()`.
3. Run the audit; paste the new "emitted by a lowering" count (was 79 of 89 encoders, 64 base mnemonics) and the unwired list (was 10; expect 8: `adrp` and `br` gone) into this file's Done section.

## Do NOT
- Do not delete `ASSEMBLER_EMITTED["adrp"]` (a pinned test requires it).
- Do not add a lowering for `br`: no source construct needs it; this step is a measurement fix.
- Do not edit `bugs/FORMAL_arm64_instruction_coverage.md` (the source doc is wrong on this point; the coordinator's report says so).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 4 --label t -- python3 test_arm64_encoders.py
python3 tools/memslot.py --gb 4 --label t -- python3 test_formal_isa_census.py
python3 tools/arm64_insn_audit.py | sed -n 1,30p
```

## Done when
- [x] audit's unwired list no longer names `encode_br_xn` or `encode_adrp`; `br` not in the uncovered top list
- [x] both test files pass; the pinned-basenames assertion names the linker
- [x] the audit prints the `EMITTED_ONLY_BY_STUB` line

## Done
- audit: 91 encoders (70 base mnemonics), emitted by a lowering 86 (69). Unwired down to 5 (`cset_wd_cond`, `ldp_xt1_xt2_rn`, `ldr_xt_sp_imm`, `movn_wd_imm`, `str_xt_sp_imm`) — `encode_br_xn` and `encode_adrp` removed. `EMITTED_ONLY_BY_STUB` added for `br` (linker stub). `ASSEMBLER_EMITTED["adrp"]` reworded.
- `test_arm64_encoders.py` passes (932 PASS). `tools/arm64_insn_audit.py` and `tools/formal_isa_census.py` LEVER_ROOTS already agreed on linker scope; audit now matches.

## If stuck
If the census test starts failing after the scope change, paste its first failing assertion in "Blocked" and revert only your own `lowering_files()` edit.
