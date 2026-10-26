# The arm64 proof generator's `sp`/frame trackers drop the `ADD`/`SUB` immediate's `sh` field — a SECOND cause of the `call_proofgen` reds

**Area:** FORMAL, `formal/arm64_proof_gen.py`'s ADD/SUB-immediate decodes.
**Status: OPEN, MEASURED, and the fix is written and verified (patch at the
end) but NOT landed — the symptom it shares with the rest of the oct-7
`test_formal_call_proof_gen.py` reds is `maxRecDepth` on an `sp`-arithmetic step,
which `f7bd05ea` closed for its own half; this half is a different mechanism, so
this doc is filed rather than edited under that one.**

This is a **distinct root cause** from the one that half names, not a duplicate
of it: that half says the reds come from the non-reducible `arm64_ext_imm12 w`
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

## The patch, verbatim

```diff
diff --git a/formal/arm64_proof_gen.py b/formal/arm64_proof_gen.py
index f3b22147..4478bfba 100644
--- a/formal/arm64_proof_gen.py
+++ b/formal/arm64_proof_gen.py
@@ -3672,6 +3672,23 @@ _I12 = "(((w >>> 10) &&& 0xfff).toNat)"
 _I16 = "(((w >>> 5) &&& 0xffff).toNat)"
 _HW = "(((w >>> 21) &&& 0x3).toNat)"
 _I7 = "(((w >>> 15) &&& 0x7f).toNat)"
+def _addsub_imm12(w: int) -> int:
+    """The `ADD`/`SUB` (immediate) operand: `imm12` (bits 21:10) scaled by the
+    `sh` field (bits 23:22), which selects `LSL #0` or `LSL #12`.
+
+    `lib/ProofLib.lean::arm64_ext_imm12` is the MODEL's copy of this decode and
+    `_step_rhs` is the generator's; this is the ONE Python copy every `sp` and
+    frame tracker below reads.  A tracker that re-derived `(w >> 10) & 0xfff`
+    dropped the shift and computed `#32` where the machine moves `#32, lsl #12`
+    — the same duplicate-decoder defect the model had and `5361903f` fixed,
+    one layer down, and it is
+    what left `count`'s `hcond` rewrite looking for `sp - 32 - 16` against a
+    state holding `sp - 131072 - 16`.  `sh >= 2` is RESERVED and the arm's mask
+    keeps bit 23, so only 0 and 1 can occur; `& 0x1` keeps the shift total
+    without ever computing an immediate no instruction can encode.
+    """
+    return ((w >> 10) & 0xfff) << (12 * ((w >> 22) & 0x1))
+
 _BASE = f"(if {_RN} = 31 then s.sp else arm64_reg {_RN} s)"
 _IMM26 = "((w &&& 0x03ffffff) : UInt32)"
 _IMM19 = "(((w >>> 5) &&& 0x7ffff) : UInt32)"
@@ -3993,10 +4010,10 @@ def _frame_ldp_addrs(blocks_path, words: dict, state: str):
                 sp = f"({sp} + UInt64.ofNat {imm7 * 8})"
             elif idx in (11, 12):
                 if ((w >> 5) & 0x1f) == 31 and (w & 0x1f) == 31:
-                    sp = f"({sp} - UInt64.ofNat {(w >> 10) & 0xfff})"
+                    sp = f"({sp} - UInt64.ofNat {_addsub_imm12(w)})"
             elif idx in (9, 10):
                 if ((w >> 5) & 0x1f) == 31 and (w & 0x1f) == 31:
-                    sp = f"({sp} + UInt64.ofNat {(w >> 10) & 0xfff})"
+                    sp = f"({sp} + UInt64.ofNat {_addsub_imm12(w)})"
     return addrs
 
 
@@ -4493,10 +4510,10 @@ def _frame_read_addrs(block, words: dict, state: str):
             sp = f"({sp} + UInt64.ofNat {imm7 * 8})"
         elif idx in (11, 12):  # SUB immediate (only when writing sp)
             if ((w >> 5) & 0x1f) == 31 and (w & 0x1f) == 31:
-                sp = f"({sp} - UInt64.ofNat {(w >> 10) & 0xfff})"
+                sp = f"({sp} - UInt64.ofNat {_addsub_imm12(w)})"
         elif idx in (9, 10):  # ADD immediate (only when writing sp)
             if ((w >> 5) & 0x1f) == 31 and (w & 0x1f) == 31:
-                sp = f"({sp} + UInt64.ofNat {(w >> 10) & 0xfff})"
+                sp = f"({sp} + UInt64.ofNat {_addsub_imm12(w)})"
     return out
 
 
@@ -4530,10 +4547,10 @@ def _hcond_mem_rws(all_instrs, cur_instrs, words: dict, state: str):
             sp = f"({sp} + UInt64.ofNat {imm7 * 8})"
         elif idx in (11, 12):
             if ((w >> 5) & 0x1f) == 31 and (w & 0x1f) == 31:
-                sp = f"({sp} - UInt64.ofNat {(w >> 10) & 0xfff})"
+                sp = f"({sp} - UInt64.ofNat {_addsub_imm12(w)})"
         elif idx in (9, 10):
             if ((w >> 5) & 0x1f) == 31 and (w & 0x1f) == 31:
-                sp = f"({sp} + UInt64.ofNat {(w >> 10) & 0xfff})"
+                sp = f"({sp} + UInt64.ofNat {_addsub_imm12(w)})"
     rws = []
     for ri in range(len(events) - 1, -1, -1):
         kind, addr, pc = events[ri]
@@ -4573,9 +4590,9 @@ def _sp_stores(words: dict, instrs, sp_off: int, stores: list) -> int:
             imm7 = (w >> 15) & 0x7f
             sp_off += imm7 * 8
         elif idx in (9, 10) and rn == 31 and rd == 31:
-            sp_off += (w >> 10) & 0xfff
+            sp_off += _addsub_imm12(w)
         elif idx in (11, 12) and rn == 31 and rd == 31:
-            sp_off -= (w >> 10) & 0xfff
+            sp_off -= _addsub_imm12(w)
     return sp_off
 
 
@@ -9582,10 +9599,10 @@ def _frame_stack_depths(words: dict, entry: int, end: int) -> list:
             sp += (imm7 - 128 if imm7 >= 64 else imm7) * 8
         elif idx in (11, 12):           # SUB Xd, Xn, #imm
             if (w >> 5) & 0x1f == 31:
-                sp -= ((w >> 10) & 0xfff) * 8
+                sp -= _addsub_imm12(w) * 8
         elif idx in (9, 10):            # ADD Xd, Xn, #imm
             if (w >> 5) & 0x1f == 31 and (w & 0x1f) == 31:
-                sp += ((w >> 10) & 0xfff) * 8
+                sp += _addsub_imm12(w) * 8
     return sorted(out)
 
 
@@ -11702,7 +11719,7 @@ def _frame_slot_accesses(words: dict, entry: int, end: int):
         rd, rn = w & 0x1f, (w >> 5) & 0x1f
         if idx in (9, 10):              # ADD Xd, Xn, #imm (32- and 64-bit)
             if rn in recv:
-                recv[rd] = recv[rn] + ((w >> 10) & 0xfff) * 8
+                recv[rd] = recv[rn] + _addsub_imm12(w) * 8
         elif idx == 1:                  # MOV Xd, Xn
             if rn in recv:
                 recv[rd] = recv[rn]
@@ -11738,10 +11755,10 @@ def _frame_store_depths(words: dict, entry: int, end: int) -> list:
                 out.append(-sp)
         elif idx in (11, 12):           # SUB Xd, Xn, #imm
             if (w >> 5) & 0x1f == 31:
-                sp -= ((w >> 10) & 0xfff) * 8
+                sp -= _addsub_imm12(w) * 8
         elif idx in (9, 10):             # ADD Xd, Xn, #imm
             if (w >> 5) & 0x1f == 31 and (w & 0x1f) == 31:
-                sp += ((w >> 10) & 0xfff) * 8
+                sp += _addsub_imm12(w) * 8
     return sorted(set(out))
 
 
@@ -11941,10 +11958,10 @@ def _frame_store_writes(words: dict, m: dict) -> list:
             sp += (imm7 - 128 if imm7 >= 64 else imm7) * 8
         elif idx in (11, 12):               # SUB Xd, Xn, #imm
             if (w >> 5) & 0x1f == 31:
-                sp -= ((w >> 10) & 0xfff) * 8
+                sp -= _addsub_imm12(w) * 8
         elif idx in (9, 10):                # ADD Xd, Xn, #imm
             if (w >> 5) & 0x1f == 31 and (w & 0x1f) == 31:
-                sp += ((w >> 10) & 0xfff) * 8
+                sp += _addsub_imm12(w) * 8
         elif idx == 31:                     # STR [Xn, #imm]: the receiver frame
             out.append((None, True))
     return out
```
