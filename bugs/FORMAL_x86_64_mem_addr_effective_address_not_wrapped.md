# FORMAL: `x86_mem_addr` does not wrap the effective address to 64 bits

Found while landing the fuzz draw for the two SIB-indexed byte forms
(`formal/x86_64_model_fuzz.py`'s `mov_rm8_r8_idx` / `movzx_r64_rm8_idx`
entries). It is NOT the coverage bug those closed, and it is not fixed here.

## Symptom, measured

One `movzx rax, [r13+r14]` program through `formal/x86_64_model_fuzz.py`'s
harness, run twice with the same machine state except R14:

    R14 = 3            AGREE
    R14 = 2**64 - 1    WRONG  rax hw=0x13 model=0x0

R13 is `MEMBASE_ABS` (`REGION_BASE + DATA_OFF + 64`), so `R13 + (2**64 - 1)`
wraps on the CPU to `MEMBASE_ABS - 1`, which is window offset 63 — the byte the
hardware loaded (`0x13`). `lib/X86.lean`'s `x86_mem_addr` computes

    some ((Int.ofNat (base + indexContribution) + disp).toNat, ...)

with `Nat`/`Int` arithmetic and no truncation, so the model's address is
`MEMBASE_ABS + 2**64 - 1`; `mem_N` answers `0` for anything outside
`[dataLo, dataLo+dataN)`, and the model reports `rax = 0`.

Reproduce: build a `formal/x86_64_model_fuzz.Program` with
`X.encode_movzx_r64_rm8_idx(R.RAX, R.R13, R.R14)`,
`regs[R13] = F.MEMBASE_ABS`, `regs[R14] = 2**64 - 1`, and pass it to
`F.evaluate`. A positive control at `R14 = 3` agrees, so the harness path
itself is fine.

## Why this is a model bug and not a harness limit

An x86-64 effective address is the base + index*scale + displacement computed
modulo 2^64, and the model is handed the absolute region address both halves
share, so it can and should express that sum. The pool does not currently draw
it: `_index_off` deliberately draws a non-negative offset, because an index
register holding `2^64 - n` is exactly the case this doc describes and would
otherwise make the new `base + index` coverage rows `WRONG` for a reason that
has nothing to do with the SIB form.

## What the fix has to touch

`lib/X86.lean::x86_mem_addr`, the one place the effective address is computed
(the decoder comment in `formal/x86_64_decode.py::_modrm_fields` says so). The
truncation belongs on the FINAL address, after the signed displacement is
added:

    some ((Int.ofNat (base + indexContribution) + disp).toNat % 2^64, ...)

Two things make this more than a one-line edit, and they are the next step:

1. `x86_mem_addr` is unfolded by `simp` in most of the per-instruction lemmas
   in `lib/X86.lean` (`simp [x86_step, …, x86_mem_addr, …]`, and the
   proof generators' closing tactics). A `% 2^64` on a symbolic sum will not
   reduce the way the current expression does, so the lemmas that quote an
   address (the ones whose comments say "the conclusion quotes the MODEL's own
   index expression") need either a hypothesis that the sum is below 2^64 (true
   of every real frame address) or a `Nat.mod_eq_of_lt` rewrite in their simp
   set.
2. The same question applies to the RIP-relative arm (`base = endAddr`) and to
   `[base + disp]` when `disp` is a full disp32 and the base is near the top of
   the address space. They are not separately reachable through this backend's
   emitted images, but the fix should be stated once, in `x86_mem_addr`, rather
   than per form.

## Done when

`formal/x86_64_model_fuzz.py` draws an index register at least once with a value
whose sum with the base wraps (`_index_off` can then lose its "non-negative
only" restriction and state why), the program above reports `AGREE`, and
`python3 tools/suite.py x86` plus the `proofs` bucket it depends on are green.
