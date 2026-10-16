# The method-frame depth helpers mis-scale `ADD/SUB SP, SP, #imm12`

**Area:** FORMAL, arm64 proof generator's frame/method machinery —
`formal/arm64_proof_gen.py`'s `_frame_stack_depths`, `_frame_slot_accesses`,
`_frame_store_depths` and `_frame_store_writes`.

**Status: OPEN, measured 2026-10-13 (`work/formal393-docs`), while fixing the
same `imm12` shift in the `sp`-EXPRESSION trackers
(`_frame_ldp_addrs` / `_frame_read_addrs` / `_hcond_mem_rws` / `_sp_stores`).
Not fixed here: the four functions below are the helpers
`bugs/FORMAL_a_one_field_mutator_has_no_method_contract.md` also names, that doc
is CLAIMED by `formal389-docs`, and a fix cannot be verified without a
method/dylib proof this worker may not run.**

## What I ran

A synthetic word list, no Lean, through the generator's own helper:

```python
>>> import sys, struct; sys.path.insert(0, ".")
>>> from formal import arm64 as A
>>> from formal.arm64_proof_gen import _frame_stack_depths
>>> sub16 = struct.unpack("<I", A.encode_sub_xd_xn_imm_sh(31, 31, 16, 0))[0]
>>> sub4k = struct.unpack("<I", A.encode_sub_xd_xn_imm_sh(31, 31, 1, 1))[0]  # lsl #12
>>> stp   = 0xa9bf7bfd                    # stp x29, x30, [sp, #-16]!
>>> _frame_stack_depths({0x0: sub16, 0x4: stp}, 0x0, 0x8)
[136, 144]
>>> _frame_stack_depths({0x0: sub4k, 0x4: stp}, 0x0, 0x8)
[16, 24]
```

## What I expected

`sub sp, sp, #16` moves `sp` 16 BYTES, and the `stp` stores at `sp - 16` /
`sp - 8` relative to that, so the two depths are `24` and `32`.  With
`sub sp, sp, #1, lsl #12` (= 4096 bytes) they are `4104` and `4112`.  The
function's OWN docstring says the numbers are "the ones the canonicalising simp
set (`u64_sub_sub`, `u64_sub_add`) produces", and its `STP`/`LDP` arms use
`imm7 * 8` — BYTES — so the `ADD`/`SUB` arms must be bytes too.

## What is wrong

All four helpers decode the `ADD/SUB (immediate)` displacement as
`((w >> 10) & 0xfff) * 8`, which is wrong twice:

* it drops the `sh` field at bits 23:22, so `#1, lsl #12` is read as `1` and
  not `4096`; and
* it scales by 8, which no `ADD/SUB SP, SP, #imm12` does — the field is a byte
  count.  (The `* 8` is right in `_frame_slot_accesses`'s `LDR`/`STR` arm at
  `:11663`, where it IS the access-size scaling; that one is NOT a bug.)

Sites, all four the same expression:

| function | sites |
|---|---|
| `_frame_stack_depths` (`:9507`) | `:9536`, `:9539` |
| `_frame_slot_accesses` (`:11639`) | `:11656` (the `ADD` arm only) |
| `_frame_store_depths` (`:11670`) | `:11692`, `:11695` |
| `_frame_store_writes` (`:11870`) | `:11895`, `:11898` |

## The exact next step

Replace `((w >> 10) & 0xfff) * 8` with `_ext_imm12(w)` — the Python twin of
`lib/ProofLib.lean`'s `arm64_ext_imm12`, added 2026-10-13 for the
`sp`-expression trackers and pinned by
`test_formal_call_proof_gen.py::TestTheImmediateShiftReachesTheAddressTrackers`
— at the four `ADD`/`SUB` sites above, and leave the `LDR`/`STR` `* 8` alone.
Then pin it with a hand-built word list, exactly as in "What I ran": a
`sub sp, sp, #16` plus a `stp` must give `[24, 32]`, and `sub sp, sp, #1,
lsl #12` must give `[4104, 4112]`.  Because the consumers are method/dylib
frame CONTRACTS, a green unit test is necessary but not sufficient: the change
has to be re-checked on a method proof and a dylib proof before the doc for
this goes, and both are `EXPECTED_FAILURES` today for unrelated reasons (the
value model), which is why this is filed rather than landed.

## Relationship to the other `imm12` work

This is the same defect the `sp`-EXPRESSION trackers had
(`bugs/FORMAL_arm64_the_extended_immediate_arms_ignore_their_shift.md` is the
model-side doc; the generator-side fix for the expression trackers landed
2026-10-13).  These four are the remaining generator sites that read the field
raw.  They were not reached by `fact`/`pow2`/`sqsum`/`sum` (whose proofs the
fix turned green) because those are recursion examples, not methods.
