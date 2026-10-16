# FORMAL: four contract-slot `sp` trackers read the `ADD`/`SUB` immediate and multiply it by 8

**Area:** FORMAL — `formal/arm64_proof_gen.py`'s contract-slot walkers,
`_frame_stack_depths`, `_frame_slot_accesses`, `_frame_store_depths` and
`_frame_store_writes` (the `FrameBelow` / receiver-slot depths a dylib
contract is stated over).

**Status: OPEN, measured with a direct probe, and NOT landed** — the fix is
mechanical but it feeds the whole arm64 contract corpus, which a bounded worker
cannot Lean-verify (see the last section). Filed rather than fixed, per the
worker's own rule, and filed because it is the SAME decode defect the `hcond`
`sp` trackers had and the same `_addsub_imm` closes.

## What is wrong

An `ADD`/`SUB` (immediate) instruction's `imm12` (bits 21:10) is in BYTES, with
bit 22 selecting `LSL #0` / `LSL #12`. The four BYTE-LEVEL `sp` trackers that
build Lean expressions (`_frame_ldp_addrs`, `_frame_read_addrs`,
`_hcond_mem_rws`, `_sp_stores`) now read it through `_addsub_imm`, which applies
both. The four INTEGER-depth trackers still have the older form, and it is wrong
in two independent ways:

```python
    elif idx in (11, 12):           # SUB Xd, Xn, #imm
        if (w >> 5) & 0x1f == 31:
            sp -= ((w >> 10) & 0xfff) * 8      # (a) no `sh`, (b) *8
```

* the immediate is already in bytes, so `* 8` is a factor-of-8 error — the
  scaling that IS right for an `LDR`/`STR` unsigned-offset `imm12` (which the
  encoder scales by the access size) was copied onto the ADD/SUB arm, where
  nothing scales it; and
* `sh` (bit 22) is dropped, so `sub sp, sp, #131072` — the frame scratch,
  emitted as `32 << 12` by `formal/arm64_codegen.py::_emit_imm_shift12` — reads
  as `32 * 8 = 256` rather than `131072`.

## The probe

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 -c "
import struct
import formal.arm64_proof_gen as G
from formal.arm64 import encode_sub_xd_xn_imm, encode_stp_sp_pre
words = {0x1000: struct.unpack('<I', encode_sub_xd_xn_imm(31,31,32))[0],
         0x1004: struct.unpack('<I', encode_stp_sp_pre(0,1))[0]}
print(G._frame_stack_depths(words, 0x1000, 0x1008))"
[264, 272]
```

`sub sp, sp, #32` then `stp x0, x1, [sp, #-16]!` stores at **48** and **56**
bytes below the entry `sp`; the tracker reports 264 and 272. `_frame_slot_accesses`
has the same `* 8` on its `ADD` arm (its `LDR`/`STR` arm's `* 8` is CORRECT and
must stay), and `_frame_store_depths` / `_frame_store_writes` have it on both the
`ADD` and `SUB` arms.

## Why it is not landed here

`sp0 - c` for every reported `c` becomes a `Frame.FrameBelow` premise of the
method's contract (`formal/arm64_proof_gen.py`, the `hyps` list around the
`Frame.FrameBelow (UInt64.ofNat {sp0} - UInt64.ofNat {c})` line). A wrong `c` is
therefore a premise about the wrong address, so this is not a diagnostic change:
it decides whether every arm64 dylib contract is stated about the method's real
frame. The fix is four sites and `_addsub_imm` already exists, but the change is
only exercised end to end by `python3 test_formal.py` (the 93-proof corpus,
46 GB, over every per-job ceiling a light worker has) — and the two cheaper
suites the worker CAN run do not move:
`python3 test_formal_call_proof_gen.py` stays 7 red and
`python3 test_formal_dylib.py` stays 24/2 with the fix applied, which is a
statement that these two do not reach a method whose range contains an ADD/SUB
`sp`, not that the `*8` is right.

**The exact next step for whoever can run it:** apply `_addsub_imm(w)` to the
`ADD`/`SUB` arms of those four functions (leaving the `LDR`/`STR` arm's `* 8`
alone), add a unit row matching the probe above for each of them, run
`python3 test_formal.py` before and after, and keep it only if the corpus is no
worse. `bugs/FORMAL_call_proofgen_reds_after_the_arm64_model_merge.md` is the
doc that owns the arm64 contract corpus's current reds.
