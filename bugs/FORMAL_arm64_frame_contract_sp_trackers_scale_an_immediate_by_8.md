# The frame-contract sp trackers scale an ADD/SUB immediate by 8 AND drop its `sh` bit

**Area:** FORMAL, arm64 — `formal/arm64_proof_gen.py`'s METHOD-frame-contract
trackers. **Found 2026-10-12 (`work/formal270-docs-r2`)** while fixing the same
field in the four trackers on the CFG walk's own path (`_imm12_scaled`; see
`bugs/FORMAL_eighteen_examples_have_no_accepted_proof_and_seven_are_declared.md`'s
2026-10-12 Status). **NOT FIXED** — the three functions below feed the
method-frame contract, which no corpus example reaches today, so a fix here
would be unverifiable with the narrow suites; this doc is the measurement.

## What was run

An audit of every Python-side reader of an `ADD`/`SUB (immediate)`'s 12-bit
field (`_STEP_CONDS` indices 9/10 ADD, 11/12 SUB). The instruction's immediate is
a BYTE count, scaled by `sh` (bit 22): `arm64_ext_imm12 insn = imm12 << (12 *
sh)`. Four readers on the walk's own path got the `sh` bit wrong and are fixed;
these three compute a byte offset AND multiply the field by 8 as well, which is
the same arithmetic the `STP`/`LDP` arms use for their `imm7` (an 8-byte count)
and is not what an `ADD`/`SUB` immediate is.

## What was seen

    formal/arm64_proof_gen.py:9533-9538   _frame_stack_depths
        elif idx in (11, 12):           # SUB Xd, Xn, #imm
            if (w >> 5) & 0x1f == 31:
                sp -= ((w >> 10) & 0xfff) * 8
        elif idx in (9, 10):            # ADD Xd, Xn, #imm
            if (w >> 5) & 0x1f == 31 and (w & 0x1f) == 31:
                sp += ((w >> 10) & 0xfff) * 8

    formal/arm64_proof_gen.py:11653-11655 _frame_slot_accesses
        if idx in (9, 10):              # ADD Xd, Xn, #imm (32- and 64-bit)
            if rn in recv:
                recv[rd] = recv[rn] + ((w >> 10) & 0xfff) * 8

    formal/arm64_proof_gen.py:11689-11694 _frame_store_depths
        elif idx in (11, 12):           # SUB Xd, Xn, #imm
            if (w >> 5) & 0x1f == 31:
                sp -= ((w >> 10) & 0xfff) * 8
        elif idx in (9, 10):             # ADD Xd, Xn, #imm
            if (w >> 5) & 0x1f == 31 and (w & 0x1f) == 31:
                sp += ((w >> 10) & 0xfff) * 8

Two errors each: the missing `sh` scale (so `sub sp, sp, #32, lsl #12` is 32, not
131072) and the spurious `* 8` (so even an unshifted `sub sp, sp, #16` is 128,
not 16). `_frame_stack_depths`'s own docstring says the numbers must be "the
ones the canonicalising simp set (`u64_sub_sub`, `u64_sub_add`) produces" — byte
depths — and its caller uses them as bytes in
`Frame.FrameBelow (UInt64.ofNat sp0 - UInt64.ofNat c)`, which is what makes both
halves wrong rather than a units convention:

    formal/arm64_proof_gen.py:12007-12019
        depths = _frame_stack_depths(words, m["entry"], m["end"])
        ...
        hyps.append((f"hsep{c}", f"Frame.FrameBelow "
                                   f"(UInt64.ofNat {sp0} - UInt64.ofNat {c}) "
                                   f"n 1", None))

The `STP`/`LDP` arms in the same functions use `(signed imm7) * 8` — correct,
because `imm7` IS an 8-byte count — which is why the `* 8` reads as a copy-paste
of those arms rather than a second convention.

## Expected

`sp -= _imm12_scaled(w)` (or the equivalent with the caller's convention) and the
`recv[rd] + _imm12_scaled(w)` for the `ADD` form, i.e. the same reader the four
fixed trackers now call.

## Next step

Change the three sites to `_imm12_scaled(w)` and drop the `* 8`. **It needs a
corpus example that REACHES a method-frame contract to be verifiable**: today the
only method examples (`wide_recv`, `struct_method`, `struct_point`) are refused
before the contract is generated (a struct construction has no model), and
`bugs/FORMAL_a_one_field_mutator_has_no_method_contract.md` says the mutator is
unreachable for the same reason. So a taker should first land or find such an
example (or a `_frame_methods`-shaped unit test that reads the emitted `hsep`
depths), then fix these three, then re-run `test_formal_call_proof_gen.py` —
which is where a wrong depth would surface.
