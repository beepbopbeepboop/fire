# FORMAL_arm64_three_frame_depth_trackers_still_drop_the_addsub_immediate_shift

**Area:** FORMAL, the arm64 proof generator's frame-depth trackers.
**Status: OPEN, LATENT, filed 2026-10-14 (`work/formal412-docs`) while fixing
the same omission in the four `sp` trackers that DID fire.** This is the
receiver/one-field-mutator half of that fix and it is not measured to be
reachable today; it is filed so nobody has to re-derive it if it turns out to
be.

## What the sibling fix was

`formal/arm64_proof_gen.py::_addsub_imm` now scales an `ADD`/`SUB` (immediate)
by its `sh` field (bits 23:22; `LSL #0`/`LSL #12`), and the four trackers that
build `sp` EXPRESSIONS for a conditional-path peel
(`_frame_ldp_addrs`, `_frame_read_addrs`, `_hcond_mem_rws`, `_sp_stores`) use
it.  Before that, the codegen's 128KB scratch — `sub sp, sp, #32, lsl #12`,
`formal/arm64.py::encode_sub_xd_xn_imm_sh`, 131072 bytes — was read as `32`, so
a `hcond` spill peel addressed a slot 131040 bytes away from its store, Lean's
`rw` found no occurrence, and `ifonly`/`condassign`/`elif3`/`sgt8` were red.

## What is not fixed

Three more `sp`/offset trackers read an `ADD`/`SUB` immediate and drop `sh` the
same way.  Each also multiplies the 12-bit field by **8**, which is a second
question: an ADD/SUB immediate is in BYTES (`encode_sub_xd_xn_imm_sh`'s own
docstring: "131072 is 32 << 12"), while the `STP`/`LDP` `imm7` in the same
functions is in 8-byte units and is correctly scaled by 8, so the two branches
in one tracker currently use different units.

| line | tracker | the line |
|---|---|---|
| `formal/arm64_proof_gen.py` `_frame_store_depths` | method frame depths for a receiver contract | `sp -= ((w >> 10) & 0xfff) * 8` / `sp += ((w >> 10) & 0xfff) * 8` |
| `formal/arm64_proof_gen.py` `_frame_store_writes` | the same, per memory write | same two lines |
| `formal/arm64_proof_gen.py` `_receiver_offsets` (the `recv` loop, `idx in (9, 10)`) | register byte-offset from the receiver | `recv[rd] = recv[rn] + ((w >> 10) & 0xfff) * 8` |

For the byte convention the correct terms are `_addsub_imm(w)` with no `* 8`
(the `* 8` is right only for the `LDR`/`STR` access scale in the same loop, not
for the `ADD`/`SUB`).

## Why it may not be reachable

All three scan a METHOD's `[entry, end)`, and the two frame-store trackers'
docstrings say their subject is the method's own `STP Xt1, Xt2, [SP, #-K]!`
stores — the frame is built with `STP`, and the 128KB scratch that needs
`lsl #12` is emitted at list/dict/comprehension bases rather than in a
one-field method's prologue.  So the `ADD`/`SUB` branch may be a copy that
never fires.  That is a guess and not a measurement.

## The exact next step

1. Measure whether the branch fires: add a one-line print (or a counter) to
   the `idx in (9, 10)` / `(11, 12)` arms of the three functions and run the
   receiver-frame suites — `test_formal_dylib.py`, `test_formal_run.py`'s
   one-word-field groups, `test_formal_returned_frame.py` — over an image that
   puts an ADD/SUB on `sp` inside a method.
2. If it fires, fix all three to `_addsub_imm(w)` with the byte unit; the
   pinned program is `test_formal_eval_eq_mojo_bridge.py`'s twelve-spilled-locals
   fixture (a `STUR`/`LDUR` pair at `[x29, #-0x58]`), which is the shape that
   already needs the unscaled form.
3. If it does not fire, delete this doc rather than leave it: a branch no run
   reaches is not a bug, and a doc for one is the queue growing faster than the
   work.
