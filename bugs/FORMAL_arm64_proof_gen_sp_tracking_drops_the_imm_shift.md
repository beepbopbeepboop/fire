# The arm64 proof generator's `sp`/frame trackers drop the `ADD`/`SUB` immediate's `sh` field — a SECOND cause of the `call_proofgen` reds

**Area:** FORMAL, `formal/arm64_proof_gen.py`'s ADD/SUB-immediate decodes.
**Status: OPEN, MEASURED, and the fix is written and verified (patch at the
end) but NOT landed — the symptom is `bunny-proofgen`'s claim
(`FORMAL_call_proofgen_reds_after_the_arm64_model_merge.md`), so this is filed
rather than edited.**

This is a **distinct root cause** from the one that doc names, not a duplicate
of it: that doc says the reds come from the non-reducible `arm64_ext_imm12 w`
term in `work_step_add_imm64`'s STATEMENT (`lib/ProofLib.lean`), which makes the
elaborator exceed `maxRecDepth`.  This one is in the GENERATOR, and no change to
the library lemma touches it.

## What is wrong

The model (`lib/ProofLib.lean::arm64_ext_imm12`) and `_step_rhs` both decode the
`ADD`/`SUB` (immediate) operand as `imm12 << (12 * sh)`, where `imm12` is bits
21:10 and `sh` is bits 23:22.  Every OTHER decoder in the generator re-derives
`(w >> 10) & 0xfff` and **drops the shift** — the exact duplicate-decoder defect
fixed in the model by `5361903f` (`arm64 model: ADDS writes Rd, and the imm12
arms honour their shift`, one `arm64_ext_imm12` helper all five `imm12` arms
call), one layer down.  So for the frame teardown `add sp, sp, #32, lsl #12`
the model moves `sp` by **131072** and the trackers compute **32**.

Measured, `count` on arm64 (`prove=True`, `check=False`): the generated `hcond`
rewrite looks for

    mem_read_two_writes_adj_uint _ (((s_0).sp - UInt64.ofNat 32) - UInt64.ofNat 16) _ _

against a target expression whose state holds `s_0.sp - UInt64.ofNat 131072 -
UInt64.ofNat 16`, so the `rw` fails ("Did not find an occurrence of the
pattern").  Same for `s_1`, and the same shape appears in every arm64 example
with a frame at or above `4096` bytes (`absval`, `bigconst`, `both`,
`cmp_le_ge`, `condassign`, `deepif`, `early_ret`, `either`, `fact`, `fib`,
`ifonly`, `nonzero`, `pow2`, `sgt8`, `sign`, `sle8`, `sqsum`, `sum`,
`toplevel_*`, `twoifs`, `ug8`, …): 44 of the 93 `formal/examples` on arm64.

## The sites

`(w >> 10) & 0xfff` in an `idx in (9, 10)` / `idx in (11, 12)` arm (ADD/SUB
immediate), with no `<< (12 * ((w >> 22) & 1))`:

| function | what it tracks |
|---|---|
| `_frame_read_addrs` (two copies, `return addrs` / `return out`) | the `sp` expression at an `LDP` |
| `_hcond_mem_rws` | the `sp` expression for a condition block's spill read |
| `_sp_stores` | the byte offset of the caller's frame slots |
| `_frame_stack_depths` | signed stack depths |
| `_self_accesses`, and the two receiver-frame trackers near them | frame accesses |

`_step_rhs` (correct) and `_known_reg`'s `idx in (9, 10)` arm (correct — it
shifts with `if (w >> 22) & 1: imm <<= 12`) are the controls: the same decode is
already right in two places, which is why this is a consolidation and not a new
idea.  `(w >> 10) & 0xfff` in `idx == 18/19/31/54-61` is LDR/STR, a class with
no `sh` field, and must NOT change.

## The fix (written, verified, not landed)

One helper beside the other decode constants:

```python
def _addsub_imm12(w: int) -> int:
    return ((w >> 10) & 0xfff) << (12 * ((w >> 22) & 0x1))
```

and every ADD/SUB-immediate site reads it.  `_addsub_imm12` returns the same
number as before for `sh = 0` (small frames), so only the large-frame programs'
proofs move, and they move from the unshifted offset to the model's shifted one
— `sp - 32 - 16` becomes `sp - 131072 - 16`.  The 186 example proofs were
regenerated both ways: the 93 x86-64 proofs are byte-identical, and the arm64
ones differ only in these offsets.

## Reproduce

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 -c "
import sys,os; sys.path.insert(0,'.')
import formal.build as fb
fb.compile_formal('formal/examples/count.mojo', arch='arm64',
                  output='.tmp/count.aout', prove=True, check=False)"
grep -n 'mem_read_two_writes_adj_uint _ ' .tmp/count_proof.lean
#   the offset is UInt64.ofNat 32; the state it must match holds 131072
```
