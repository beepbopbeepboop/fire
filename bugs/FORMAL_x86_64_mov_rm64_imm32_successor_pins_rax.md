# FORMAL: `mov r/m64, imm32` is proved as `mov rax, imm32`

Found while running the end-to-end emitter against two corpus examples after the
SIB-index/effective-address fixes. It is NOT either of those bugs: the step's
`rip` is right, the encoding is decodable, and the proof still elaborates. What
is wrong is which REGISTER the successor writes, and the guard turns it into a
live hole instead of a false theorem.

## Symptom, measured

     python3 formal/x86_64_endtoend_test.py formal/examples/six_params.mojo
       six_params  terminates: proved, 1 live hole (hstep30's side condition, line 1621)
     python3 formal/x86_64_endtoend_test.py formal/examples/subscript_var.mojo
       subscript_var  terminates: proved, 1 live hole (hstep13's side condition, line 925)
       ... 402 guarded, 1 proved with a sorry

The generated step in `six_params` is

     have hstep30 : x86_step s30 rc = some { s30 with rax := 2, rip := 4294968639 }
       x86_step_mov_rax_imm32 s30 rc 4294968632 (2) ...

and the bytes at 4294968632 are `48 c7 c7 02 00 00 00` — `mov rdi, 2`, because
ModRM `c7` is mod=3, reg=0, **rm=7**. `subscript_var`'s is
`49 c7 c7 0a 00 00 00` — `mov r15, 10`. In both, the lemma's `h_b2` is
`code (m + 2) = 0xc0` while the byte is `0xc7`, so the `_BYTES` side-condition
guard admits and the file builds with one `sorry`.

## Why this is an emitter bug and not a harness limit

`formal/x86_64.py` emits `C7 /0` for `mov r/m64, imm32` at whatever destination
register the lowering picked; two corpus examples already reach rm=7 and rm=7
with REX.B. `formal/x86_64_endtoend_test.py` names the decoder's
`mov_rm64_imm32` by that form alone and maps it to a lemma pinned to RAX:

  * `_FORMS["mov_rm64_imm32"] = ("x86_step_mov_rax_imm32", True, [...])`
    (the lemma's own statement is `rax := UInt64.ofInt imm`),
  * `_SUCCS["mov_rm64_imm32"] = "{ $s with rax := $imm, rip := $next }"`,
  * `_abs_step`'s branch writes `_R_AX`.

The byte guard keeps this from becoming a WRONG claim at rm≠0 (the `h_b2` check
fails), which is exactly why it went unnoticed: it is a quiet hole, and the
registered `formal-x86-endtoend` marker already says "6 proved with a counted
hole" without naming this cause. Fixing it should REDUCE that count, and the
marker's number has to move in the same commit.

## What the fix has to touch

1. `lib/X86.lean`: state the general step, e.g.
   `x86_step_mov_rm64_imm32 (s code m rex modrm reg rm dst imm)` with
   `h_mod : modrm.toNat >>> 6 = 3`, `h_b2 : code (m + 2) = modrm`,
   `h_rm : modrm.toNat &&& 7 = rm`, `h_dst : rm + x86_rex_b rex = dst`,
   `h_dst_lt : dst < 16`, concluding
   `x86_step s code = some (x86_set_reg s dst (UInt64.ofInt imm) … rip := m + 7)`.
   Keep `x86_step_mov_rax_imm32` as the `rm=0`/`rex_b=0` corollary or update its
   callers; `x86_step_mov_rm64_r64_reg` is the shape to copy for the `dst`
   argument and the `h_dst_lt` reason.
2. `formal/x86_64_endtoend_test.py`: `_FORMS` gains `mod`, `rm`, `dst`,
   `dst_lt` and the call supplies `rex modrm reg rm dst imm`;
   `_SUCCS["mov_rm64_imm32"]` becomes
   `{ x86_set_reg $s $dst $imm with rip := $next }`; the `_resolve` branch reads
   `rm` and `dst` out of the ModRM/REX (`dst = (modrm &&& 7) + x86_rex_b rex`);
   `_abs_step`'s branch writes `dst`; `_SIMP_FORMS` then needs `x86_set_reg`
   and `x86_rex_b`.
3. `formal/x86_64_model_coverage_test.py`: add a `SUCCESSOR_FORMS` row at
   `mov rdi, 2` (`48 c7 c7 02 00 00 00`) and a step-lemma row at the same
   encoding, so a regression to the rax-only statement is red here instead of a
   hole in two examples.

## Done when

`six_params` and `subscript_var` report no live hole from this form, the new
non-rax successor/lemma rows pass in `formal/x86_64_model_coverage_test.py`, and
the `formal-x86-endtoend` marker's "N proved with a counted hole" count is
reduced to agree with the run.
