# plan/step-18c: constant propagation learns the load-first rule for a by-reference receiver
**Status: DONE 2026-11-07 (measured; found already landed).** `_frame_slot_accesses(..., is_cell_receiver=False)` exists (default unchanged) and `_frame_methods` passes True for by-reference one-field methods; `test_cell_receiver_load_first_rule`, `test_cell_receiver_store_through_wrong_reg_is_none` and `test_cell_receiver_two_rets` pass (`test_formal_frame_method_finder.py` 13/13 after 18b). Not reachable from a compiled read-modify-write method: `_frame_methods`' source gate (18b) rejects `inc`-shaped bodies before the scan, so the rule is exercised only by the hand-assembled unit tests (see the memo in `bugs/FORMAL_known_limits.md` §6.3).
Class: mid      Size: M      Depends: 18b      Blocks: 18d
Source: 18a's section (D3, open question 2); deleted doc §3 point 2 and §5 step 1 (git history 0fa4255bb^).

## Current state (verify first: 18a's section exists)
- `formal/arm64_proof_gen.py::_frame_slot_accesses(words, entry, end, body=None)` (:13633) seeds registers from `{0: 0}` ("x0 arrives as the receiver" as an OFFSET). A by-reference one-field method's first body instruction is `LDR X19, [X0]` (a load of the whole word through the receiver); `commit 0fa4255bb` added handling of the "cell-load from receiver pointer" for the single-store case.

## Decisions already made
- The rule (from the deleted doc §5.1): `x0` is a pointer to the cell; the first `LDR Xd, [x0]` (imm 0) defines `Xd := value-of-cell`, NOT an offset; slot 0 is the one slot a one-field struct has. A later `STR Xs, [x0]` is a store to slot 0 whose value register is `Xs`.
- Only straight-line bodies with ONE RET get the rule; a second exit -> return `None` (the multi-exit obligation is scaffolded in 18d, not classified here).

## Work order
1. Read `_frame_slot_accesses` fully; add the rule behind `is_cell_receiver=True` (new keyword, default False) so every existing caller is unchanged; `_frame_methods` passes True for `is_byref_onefield`.
2. Unit tests in `test_formal_frame_method_finder.py` (hand-assembled word lists, copy the style of `test_body_slots_follow_the_prologue_register_copy`): `LDR X19,[X0]; ADD X19,X19,#1; STR X19,[X0]; RET` -> accesses `[(0, False), (0, True)]`; a body that stores through `x1` instead -> `None`; two RETs -> `None`.
3. Encoders: use `formal/arm64.py` (grep `def ldr`, `def str`, `def add_imm`, `def ret`); do not hand-write hex.

## Do NOT
- Do not change the default behaviour of `_frame_slot_accesses` for existing callers.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_frame_method_finder.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] 3 new tests pass; the 5 existing pass

## If stuck
Record the encoder/shape that does not decode into §6.3 Status and stop.
