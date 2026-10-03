# `x86_step_mov_rm64_mem_disp32` does not exist, so a stack argument past the twentieth has no step lemma

**Area:** FORMAL (the x86-64 machine model). **Status: OPEN — the codegen half is
done and measured; what is missing is one theorem and one row.** Found
2026-10-02 while implementing the SysV stack-argument convention
(`bugs/FORMAL_x86_64_argument_registers.md`, now deleted — this is the only part
of it that outlived the fix).

**This is NOT a reason to lower `_MAX_INCOMING_ARGS`.** A missing step lemma is a
gap in the PROOF apparatus, and the one thing that must not happen is a working
calling convention being narrowed to suit it — that would put the tree's ability
to build programs in the hands of a theorem that has not been written, and it is
the substitution this project's own filing explicitly warned against.

## What I measured

The callee's stack-argument load is `mov r11, [rbp + 16 + 8k]`, and
`formal/x86_64.py`'s `_rm_disp` picks the narrowest encoding, so the
displacement crosses from disp8 to disp32 partway up:

```console
$ python3 -c "…encode_mov_r64_rm64(Reg.R11, Reg.RBP, 16 + 8*(i-6))…"
arg  6 disp   16 -> 4c 8b 5d 10           form=mov_r64_rm64 mode=1   (disp8)
arg 19 disp  120 -> 4c 8b 5d 78           form=mov_r64_rm64 mode=1   (disp8)
arg 20 disp  128 -> 4c 8b 9d 80 00 00 00  form=mov_r64_rm64 mode=2   (disp32)
arg 23 disp  152 -> 4c 8b 9d 98 00 00 00  form=mov_r64_rm64 mode=2   (disp32)
```

So argument index 20 — the **twenty-first** parameter — is the first that needs a
disp32 load, and `_MAX_INCOMING_ARGS` (24) permits four of them. The IMAGE is
correct: a 24-argument function builds and runs on both backends and answers
`a23 + a20 * 10 + a6` = 241 for `(1..24)`, which is the value the source says,
and it does so on x86-64 with three disp32 loads in its prologue.

**The model can STEP it.** `x86_mem_addr` reads `dispN = 4` and
`read_i32_le` for mod=2, so `x86_step` returns `some` for
`4c 8b 9d 80 00 00 00`, and `formal/x86_64_model_coverage_test.py` — which asks
the model to step everything the encoder can produce — passes.

**What is missing is the LEMMA.** `lib/X86.lean` has `x86_step_mov_mem_disp32`
(a STORE through a disp32) and `x86_step_mov_rm64_mem_disp8` (a LOAD through a
disp8), and no LOAD through a disp32. So the per-instruction proof chain cannot
be built for one, and `formal/x86_64_endtoend_test.py`'s `_shapes` names the
shape `mov_r64_rm64_disp32` and finds no row for it in `_FORMS` — which is the
designed behaviour: an unmapped addressing mode is **reported by name** rather
than proved against the wrong instruction, which is the fix for B2 in
`bugs/FORMAL_x86_64_end_to_end_proof.md`.

## Why it cannot be observed today

Two things hide it, and both are recorded here so nobody reads "the end-to-end
job is green" as coverage:

1. **`lib/X86.lean` does not elaborate on this tree.**
   `bugs/FORMAL_x86_64_step_lemma_cdq.md` has the measurement: `x86_step_cqo`
   states `cdq` where the model computes `cqo`, so the library build fails and
   `ensure_library` never gets as far as any program. Every `--formal` build
   with a proof is red, on both backends, until that is fixed.
2. **No program in the corpus is that wide.** The widest function in
   `formal/hostmods` is six parameters, and `formal/examples` is arithmetic. A
   21+-parameter function has to be written by hand to reach this.

## The exact next step

1. `lib/X86.lean`: state `x86_step_mov_rm64_mem_disp32` beside
   `x86_step_mov_rm64_mem_disp8`, in the same shape — the model is
   `x86_rm_read` at `x86_mem_addr`'s address, so the proof is the disp8 lemma's
   with `mode = 2` and a four-byte displacement, and the hypotheses are the same
   list (`rip`, `b0`..`b2`, `disp32`, `rex`, `w`, `mod`, `rm`, `rm_ne`, `reg`,
   `dst`, `dst_lt`). Copy the STORE lemma's `disp32` handling rather than the
   load's `disp`, which is `read_i8`.
2. `formal/x86_64_endtoend_test.py`'s `_FORMS`: add the row

   ```python
   "mov_r64_rm64_disp32": ("x86_step_mov_rm64_mem_disp32", False,
                           ["rip", "b0", "b1", "b2", "disp32", "rex", "w",
                            "mod", "rm", "rm_ne", "reg", "dst", "dst_lt"]),
   ```

   `x86_step_mov_rm64_mem_disp8`'s side-condition list with `disp` swapped for
   `disp32` — and the order matters, because the comment on `lea_r64_rm64_disp32`
   records the same trap for a different form: the list is in the lemma's own
   argument order after `(state) (code) (addr) (imm)`.
3. `formal/x86_64_model_coverage_test.py`'s `_memory_samples()`: add a
   `("x86_step_mov_rm64_mem_disp32", "mov r11, [rbp+128]", …)` row read back out
   of the encoder, so the new lemma's hypotheses are checked for APPLICABILITY
   the way every other one's are. That check is what `cqo` slipped past, and it
   only runs when the library builds.
4. Then a 21+-argument case belongs in `test_formal_x86_64_parity.py` beside the
   stack-argument rows, so the disp32 path is executed rather than merely
   encoded. `test_formal_x86_64_parity.py`'s arity rows stop at sixteen, which
   is the largest count whose stack slots are all disp8 — that is the number to
   move, and moving it is how this gap would have been found by a test rather
   than by reading the encoder.

Steps 1 and 2 are the fix; 3 and 4 are what keep it from rotting.