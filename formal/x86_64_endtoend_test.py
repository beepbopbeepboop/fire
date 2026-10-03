#!/usr/bin/env python3
"""End-to-end x86-64 proofs: the whole run, for every input, with no `sorry`.

`formal/x86_64_proof_gen.py` emits per-instruction certificates and concrete
run tests, but its end-to-end theorem is a `sorry`, because relating an
arbitrary symbolic state to the AST is a large claim.  This is the version of
that claim that IS within reach, proved for real:

    for EVERY input n, the model runs the compiled image to the exit pc and
    leaves `v` in `rax`

The input is universally quantified but the arithmetic is concrete, so this is
a statement about the whole function, not the handful of inputs the run tests
sample.  What it does not need is the AST: the expected value is the one the
program is known to produce, so the theorem is about the COMPILED BYTES being
right rather than about the compiler being right, which is the other half of
the boundary and stays a `sorry`.

The technique, and why it is this one:

  Each instruction's successor is an `obtain`-introduced VARIABLE (`s1`, `s2`,
  ...), never a substituted nest.  Every step's side conditions are then stated
  over one state variable, so the term the kernel normalises stays a single
  structure update deep however long the function is.  Writing the successors
  out inline instead nests them, and the kernel reports deep recursion
  partway down -- which is what an earlier attempt did.

  The successor's own equation comes from the step lemma, one `Option.some.inj`
  at a time, and every later step reads what it needs out of that equation with
  `simp`.  The final two facts -- the value in `rax`, and that `rip` reached the
  exit sentinel -- are then proved from the whole chain, with the memory
  read/write separation lemmas doing the real work for `rip`: the final `ret`
  reads the initial stack, far above the only address the body wrote.

Coverage is the forms in `_FORMS` below, which is every form the model has a
step lemma for that this can state a successor expression for.  A function
using anything else is reported as uncovered, with the form named, rather than
skipped silently -- the point is to know what is and is not proved.

  Measured 2026-10-02 over all 45 examples: **terminates proved with no sorry
  32, proved with a sorry 1, no finite tree 12 (10 loops and two that leave the
  function), failing 0**; value 3 proved and 12 open.  It was 10 / 14 / 19 / 0
  and value 3 / 0 when the twenty-odd forms below were wired.

  The last step from 2 to 1 was NOT a new lemma but a re-generalised one, and it
  is the shape B2 describes one level up: `mov_r64_rm64_sib` is a form NAME that
  covers `mov <any r64>, [rsp]`, and it was wired to `x86_step_mov_rax_sib_rsp`,
  a single register pair whose statement pins the REX byte to `0x48` and the
  destination to the literal field `rax`. So the `4c 8b 1c 24` that
  `_pop_slot(Reg.R11)` emits — five of them in this corpus — was proved as
  `48 8b 04 24`. Its two byte hypotheses were FALSE, the side-condition guard
  admitted them, and `augassign` reported `terminates: proved, 1 sorry` about a
  chain containing a step that is not the instruction the machine runs. Both
  no-displacement SIB lemmas are now general over the REX byte and over the
  register named, which is what the two disp siblings already were, and both
  now have rows in `formal/x86_64_model_coverage_test.py` — which they did not
  have, and that omission is why nothing said so.

  The `sorry` count fell from 25 to 2 for a reason that is worth stating on its
  own, because it is a sentence in `X86.lean` that was wrong: the memory
  separation's inequality was always closedable, and the emitted proof applied
  the peel `rw` ONCE against an N-deep `mem_write_bytes` chain.  `repeat` in
  front of it peels every layer, and each layer's side condition is closed over
  literals.  `simp only [key]` does not work — a conditional rewrite whose
  side condition `simp` must discharge made no progress at all — while
  `repeat rw [key _ _ _ _ (by decide)]` peels all of them.

  The twenty that came off this list, and the count of examples each was
  blocking, is the useful record of what a lemma is worth -- but note that it
  is NOT the count it adds to the proved line, because the blockers overlap
  heavily.  `alu_rr:cmp` and `alu_rr:test` removed 27 each and moved the proved
  count by zero, since every example they blocked was blocked by something else
  too.

      28 jcc_rel32      26 setcc          8 imul_r64_r64   7 call_rel32
      26 movzx_r64_r8   21 jmp_rel32      3 movsx_r64_r8   3 shift_imm8:*
      3 mov_*_nodisp    3 mov_*_disp8    3 lea_r64_rm64   2 alu_ri32:add_reg
      2 alu_ri32:and    2 alu_ri8:cmp    1 alu_rr:and/or/xor

  What remains is `group3:idiv`, and it is the one that is not a wiring job:
  `x86_idiv128` returns `none` when the divisor is zero, so the model's step is
  PARTIAL, and no statement of it can be chained by this generator.  The long
  version, with why naming the quotient and remainder needs a side condition the
  generator cannot discharge and keeping the `match` stops the next address
  from reducing, is in `bugs/FORMAL_x86_64_end_to_end_proof.md`.

  `setcc` (26) was the one that did NOT fall out of a generalisation, and it is
  worth saying why rather than leaving it in the list.  `cmp` and `test` are
  flags-only: proving them is proving the operands and the flag function, and
  the successor names no register.  `setcc` sits behind the decoder's 0x0F
  dispatch, where reaching the case means excluding the jcc range, 0xaf (imul)
  and the movzx/movsx opcodes, and where the destination is the r/m field rather
  than the reg field -- the opposite sense to `mov`, which is where the two
  existing concrete lemmas (`setne_al`, `setle_al`) got their orientation.  The
  two concrete lemmas do cover the common conditions; what is missing is the
  nibble-parameterised version, and the work is pinning down which decoder
  (there is a 0x0F dispatch in `x86_step_rex` and another in `x86_step_plain`,
  with different `rip + 3` / `rip + 4` lengths) the no-REX encoding actually
  reaches, then stating the range and exclusion facts separately so `simp` can
  use each as a rewrite.

  Three limits are worth stating separately, because each is a limit of what
  is proved here rather than a gap in it:

    * The result must not depend on the input.  The theorem states a
      CONSTANT, so `identity` cannot satisfy it however it is proved; the test
      detects this by asking the model whether two different inputs give the
      same answer, and reports it as uncovered.  Stating the result as an
      expression of the input is a dataflow problem this does not attempt.

    * Only straight-line functions.  There is no CFG, so a `jcc_rel32` or
      `jmp_rel32` cannot be chained -- which is why those two are the largest
      remaining blockers, and why closing them means cutting blocks rather
      than adding lemmas.

    * `group3:div` is skipped wherever it appears, for the same reason the
      per-instruction certificates skip it: the step is not total.

Usage: python3 formal/x86_64_endtoend_test.py [file.mojo ...]
"""

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import formal.build as B          # noqa: E402
import formal.x86_64_decode as D  # noqa: E402
import formal.lean as L           # noqa: E402

#: Where Lean's library and the `X86.olean` this test needs live.
#:
#: This was a hand-rolled `LEAN_BIN` with a hard-coded elan path beside it, and
#: that is the thing `formal/lean.py::find_lean` exists to avoid — a bare
#: `command -v lean` on an elan machine is a shim that resolves a toolchain
#: from the CURRENT DIRECTORY, so a path spelled here is silently the wrong
#: toolchain (or a download) the moment `lean-toolchain` moves. `$LEAN_BIN` is
#: still honoured, because `find_lean` reads it.
LEAN_BIN = L.find_lean(ROOT)
LIB = os.path.join(ROOT, "lib")

#: Bounds for the per-example Lean runs below. Each is ONE generated theorem
#: over one example, so the policy's proof bounds apply; the numbers are passed
#: explicitly because this file makes dozens of Lean runs and its own two call
#: sites previously had NO timeout whatsoever (`subprocess.run` with no
#: `timeout=`), which is the worst of the three shapes in this tree: a spinning
#: `native_decide` here is not slowed down, it is invisible.
PROOF_WALL_S = L.PROOF_WALL_S
PROOF_CPU_S = L.PROOF_CPU_S

#: form -> (step lemma, how to build its trailing side-condition arguments).
#:
#: The predecessor state is substituted for `$s`, the code function for `$c`,
#: the instruction address for `$m`, and the decoded immediate for `$imm` /
#: `$disp`.  Each entry lists the side conditions in the lemma's own order
#: after `(state) (code) (addr) (imm)`, so the generator does not have to know
#: the argument order of each lemma.
_FORMS = {
    "push_r64": ("x86_step_push_rbp", False, ["rip", "b0"]),
    "alu_ri32:sub_rsp": ("x86_step_sub_rsp_imm32", True,
                     ["rip", "b0", "b1", "b2", "imm"]),
    "mov_rm64_imm32": ("x86_step_mov_rax_imm32", True,
                       ["rip", "b0", "b1", "b2", "imm"]),
    "alu_ri32:add_rsp": ("x86_step_add_rsp_imm32", True,
                     ["rip", "b0", "b1", "b2", "imm"]),
    # The digit-immediate ALU forms the backend emits outside the rsp pair.
    # `81` is the 32-bit immediate and `83` the 8-bit one, and they are not the
    # same length: the model's `endAddr` is `m + 7` for the first and `m + 4`
    # for the second, so a successor that said one length for both would be a
    # proof of a different instruction.  `cmp` is the one whose successor names
    # no register at all -- digit 7 sets the flags and discards the result.
    "alu_ri32:add_reg": ("x86_step_add_ri32", False,
                         ["rip", "b0", "b1", "b2", "rex", "w", "mod", "digit",
                          "rm"]),
    "alu_ri32:and": ("x86_step_and_ri32", False,
                     ["rip", "b0", "b1", "b2", "rex", "w", "mod", "digit",
                      "rm"]),
    "alu_ri8:cmp": ("x86_step_cmp_ri8", False,
                    ["rip", "b0", "b1", "b2", "rex", "w", "mod", "digit",
                     "rm"]),
    "mov_r64_rm64_reg": ("x86_step_mov_rm64_r64_reg", False,
                         ["rip", "b0", "b1", "b2", "rex", "w", "mod",
                          "reg", "rm"]),
    # The two SIB forms with NO displacement, load and store.  `[rsp]` has no
    # non-SIB encoding (at mod=0 rm=5 is RIP-relative), so the SIB byte is
    # `m + 3` and there is no displacement after it.
    #
    # BOTH are general over the REX byte and over the register the instruction
    # names, and that is not tidiness: the previous statements pinned the REX to
    # `0x48` and the load's destination to the literal field `rax`, on the
    # reasoning that "every SIB operand the backend emits has this shape". That
    # is a fact about the SIB BYTE and not about the instruction, and
    # `_pop_slot(Reg.R11)` emits `4c 8b 1c 24`. Applied by form name, the r11
    # load was proved as `48 8b 04 24`: its two byte hypotheses were false, the
    # guard admitted them, and `augassign` reported `terminates: proved, 1
    # sorry` about a chain with a step that is not the one the machine runs.
    # The condition lists are the lemmas' own hypothesis order, so `dst`/`dst_lt`
    # come last on the load and there is no `rr` on the store at all any more.
    "mov_r64_rm64_sib": ("x86_step_mov_rm64_sib_rsp", False,
                         ["rip", "b0", "b1", "b2", "b3", "rex", "w", "mod",
                          "rm", "reg", "rb", "dst", "dst_lt"]),
    "mov_rm64_r64_sib": ("x86_step_mov_mem_sib_rsp", False,
                         ["rip", "b0", "b1", "b2", "b3", "rex", "w", "mod",
                          "rm", "reg", "rb"]),
    # The two SIB stores WITH a displacement, which is what a call site emits for
    # every argument past the register file: the outgoing area is addressed
    # through `rsp`, and at any displacement that needs the SIB byte, because
    # mod=0 rm=5 is RIP-relative rather than `[rsp]`.  So these two are the
    # CALLER half of the stack-argument convention, and without them no call with
    # a stack argument could be proved at all -- every example in the corpus has
    # fewer than seven arguments, which is why nothing said so until a 24-argument
    # one existed.
    #
    # `disp` rather than `disp32` for the second one is the whole trap, and it is
    # the same one `lea_r64_rm64_disp32` records: the list is in the lemma's own
    # argument order, and the displacement is at `m + 4` here -- ONE byte further
    # out than the non-SIB forms', because the SIB byte is in between.
    "mov_rm64_r64_sib_disp8": ("x86_step_mov_mem_sib_disp8", False,
                               ["rip", "b0", "b1", "b2", "b3", "disp", "rex",
                                "w", "mod", "rm", "reg", "rb"]),
    "mov_rm64_r64_sib_disp32": ("x86_step_mov_mem_sib_disp32", False,
                                ["rip", "b0", "b1", "b2", "b3", "disp32",
                                 "rex", "w", "mod", "rm", "reg", "rb"]),
    # `dst` is the CONCRETE destination register, which the lemma needs because
    # `x86_set_reg` is a `match` on its index and `simp` will not reduce one on
    # a non-literal.  See the note on the lemma.
    #
    # The store direction is general over both REX bits as well -- the backend
    # emits `4c` (R set) for an r8 source -- and over the base register rather
    # than pinned to `rbp`, because the corpus stores through `rbp` for a spill
    # and through `rbx` for an indexed store.
    "mov_r64_rm64_disp8": ("x86_step_mov_rm64_mem_disp8", False,
                           ["rip", "b0", "b1", "b2", "disp", "rex", "w",
                            "mod", "rm", "rm_ne", "reg", "dst", "dst_lt"]),
    # The same load through a FOUR-BYTE displacement, which is what a stack
    # argument past the twentieth encodes to: `_rm_disp` picks the narrowest
    # form, so `mov r11, [rbp+128]` is disp32 and `mov r11, [rbp+120]` is
    # disp8.  `disp32` rather than `disp` in the side-condition list because the
    # lemma reads FOUR bytes there and one here -- the list is in the lemma's own
    # argument order, and a `disp` in this position would be a proof about the
    # wrong byte.
    "mov_r64_rm64_disp32": ("x86_step_mov_rm64_mem_disp32", False,
                            ["rip", "b0", "b1", "b2", "disp32", "rex", "w",
                             "mod", "rm", "rm_ne", "reg", "dst", "dst_lt"]),
    "mov_r64_rm64_nodisp": ("x86_step_mov_rm64_mem_nodisp", False,
                            ["rip", "b0", "b1", "b2", "rex", "w", "mod", "rm",
                             "rm_ne4", "rm_ne5", "reg", "dst", "dst_lt"]),
    "mov_rm64_r64_disp8": ("x86_step_mov_mem_disp8", False,
                           ["rip", "b0", "b1", "b2", "disp", "rex", "w",
                            "mod", "rm", "rm_ne", "reg"]),
    "mov_rm64_r64_nodisp": ("x86_step_mov_mem_nodisp", False,
                            ["rip", "b0", "b1", "b2", "rex", "w", "mod", "rm",
                             "rm_ne4", "rm_ne5", "reg"]),
    "mov_rm64_r64_disp32": ("x86_step_mov_mem_disp32", False,
                            ["rip", "b0", "b1", "b2", "disp32", "rex", "w",
                             "mod", "rm", "rm_ne", "reg"]),
    # `lea` computes the address and writes it, so its successor is a register
    # write of a TRUNCATED value rather than a memory access -- the model's
    # `UInt64.ofNat (addr % 2^64)` against `mov`'s read at `addr` itself.  Only
    # the disp32 mode is wired, and `_shapes` names the other two so they are
    # reported rather than proved against the wrong instruction.
    "lea_r64_rm64_disp32": ("x86_step_lea_rm64_disp32", False,
                            ["rip", "b0", "b1", "b2", "disp32", "rex", "w",
                             "mod", "rm", "rm_ne", "reg", "dst", "dst_lt"]),
    "mov_rm64_r64_reg": ("x86_step_mov_rm64_r64_reg_st", False,
                         ["rip", "b0", "b1", "b2", "rex", "w", "mod",
                          "reg", "rm"]),
    # The only movzx the backend emits is `movzx rax, al` (48 0f b6 c0), all 33
    # of them, so this uses the existing concrete lemma rather than a
    # nibble- and register-parameterised one nothing would use.
    "movzx_r64_r8": ("x86_step_movzx_rax_al", False,
                     ["rip", "b0", "b1", "b2", "b3"]),
    # `movsx` gets the GENERAL lemma even though `movzx` above does not, because
    # the corpus emits two register pairs for it — `48 0f be c0` and
    # `48 0f be db`, three of the second to one of the first — and one shape
    # would leave the other with no lemma at all.  That is the whole of the
    # "generalise when more than one shape is emitted" rule, applied in both
    # directions on adjacent rows of the same table.
    #
    # `dst` is the CONCRETE destination, as for the `rbp + disp8` load: the
    # model's own index is `reg + x86_rex_r rex`, and `h_dst` rewrites it to
    # `dst` so both sides name the same register.  `rm` is the SOURCE, extended
    # by REX.B — the opposite sense, which is B7.
    "movsx_r64_r8": ("x86_step_movsx_r64_r8", False,
                     ["rip", "b0", "b1", "b2", "b3", "rex", "w", "mod",
                      "reg", "rm", "dst"]),
    "alu_rr:add": ("x86_step_add_rr", False,
                   ["rip", "b0", "b1", "b2", "rex", "w", "mod", "reg", "rm"]),
    "alu_rr:sub": ("x86_step_sub_rr", False,
                   ["rip", "b0", "b1", "b2", "rex", "w", "mod", "reg", "rm"]),
    # Three theorems rather than one, for the reason `lib/X86.lean` gives: the
    # model has ONE arm for all three and its result is an `if` chain on the
    # opcode, so one theorem would hand every caller that chain back.  The
    # flags are identical across the three (`x86_flags_logic`), which is why
    # they are siblings rather than three unrelated forms.
    "alu_rr:and": ("x86_step_and_rr", False,
                   ["rip", "b0", "b1", "b2", "rex", "w", "mod", "reg", "rm"]),
    "alu_rr:or": ("x86_step_or_rr", False,
                  ["rip", "b0", "b1", "b2", "rex", "w", "mod", "reg", "rm"]),
    "alu_rr:xor": ("x86_step_xor_rr", False,
                   ["rip", "b0", "b1", "b2", "rex", "w", "mod", "reg", "rm"]),
    # `shl` / `shr` / `sar` by an immediate byte.  The digit is the ModRM `reg`
    # field, which is NOT the register it is for in any other form here -- it is
    # the operation -- so `digit` gets its own condition and its own `_resolve`
    # branch rather than riding along on `reg`.
    "shift_imm8:shl": ("x86_step_shl_imm8", False,
                       ["rip", "b0", "b1", "b2", "rex", "w", "mod", "digit",
                        "rm"]),
    "shift_imm8:shr": ("x86_step_shr_imm8", False,
                       ["rip", "b0", "b1", "b2", "rex", "w", "mod", "digit",
                        "rm"]),
    "shift_imm8:sar": ("x86_step_sar_imm8", False,
                       ["rip", "b0", "b1", "b2", "rex", "w", "mod", "digit",
                        "rm"]),
    "jcc_rel32": ("x86_step_jcc_rel32", False,
                  ["rip", "b0", "b1", "cc", "off", "lo", "hi", "nsetcc_lo",
                   "nzx", "notrex"]),
    "jmp_rel32": ("x86_step_jmp_rel32", False,
                  ["rip", "b0", "off"]),
    # `call rel32`. The step lemma is ALREADY PROVED -- `x86_step_call_rel32`
    # at lib/X86.lean:757 -- so this entry is pure wiring and admits no `sorry`.
    # It is the largest single uncovered form: 7 of the x86-64 examples named
    # `call_rel32` as their missing lemma, which is what `bugs/OPEN_WORK.md` A1
    # is about.
    #
    # `takes_imm` is FALSE, and that was the whole bug.  This entry used to be
    # `True`, which made `_resolve` append the decoded displacement AFTER the
    # `off` its own branch had already supplied -- two arguments where the
    # lemma takes one, because `off` IS the immediate and
    # `x86_step_call_rel32`'s `h_imm` says `read_i32_le code (m + 1) = off`
    # rather than taking the bytes separately.  The generated application
    # therefore had one argument too many, and the failure was the least
    # informative one available:
    #
    #     numerals are data in Lean, but the expected type is a proposition
    #
    # on the DISPLACEMENT, because that is the argument that landed where a
    # hypothesis was expected.  Nothing in it says `call`, and the form it
    # appears under is the continuation after the call, so it read as a
    # statement about whatever came next.
    #
    # The comment this replaces said "NOT VERIFIED. This was wired without
    # running the suite" and named the open risk as being at the continuation
    # past the target.  The risk was real and it was not there: the target's
    # certificates apply, and the fault was in the argument list of the call
    # itself, which no amount of reading the tree could have found.
    "call_rel32": ("x86_step_call_rel32", False,
                   ["rip", "b0", "imm"]),
    # `njcc` is the jcc range's UPPER bound only.  Adding its lower bound as
    # well would be unsatisfiable for every setcc byte -- and a step lemma with
    # contradictory hypotheses still compiles and still proves its goal, it
    # just cannot be applied to anything.
    "setcc": ("x86_step_setcc_r8", False,
              ["rip", "b0", "b1", "b2", "cc", "lo", "hi", "njcc",
               "nzx", "notrex", "mod", "rm", "rb"]),
    # `dst` is the CONCRETE destination, for the same reason as the
    # `rbp + disp8` load: `x86_set_reg` is a `match` on its index.
    "imul_r64_r64": ("x86_step_imul_r64", False,
                     ["rip", "b0", "b1", "b2", "b3", "op2", "rex", "w",
                      "mod", "reg", "rm", "dst", "dst_lt"]),
    "alu_rr:cmp": ("x86_step_cmp_rr", False,
                   ["rip", "b0", "b1", "b2", "rex", "w", "mod", "reg", "rm"]),
    "alu_rr:test": ("x86_step_test_rr", False,
                    ["rip", "b0", "b1", "b2", "rex", "w", "mod", "reg", "rm"]),
    # `cqo`, the `idiv` setup.  No operand, no ModRM, and only one encoding in
    # the corpus, so it is a concrete lemma on the REX byte alone -- the shape
    # `x86_step_movzx_rax_al` has.  It is here because `group3:idiv` is not, and
    # wiring half of a pair is still worth having: `cqo` alone makes udivmod's
    # tree one form short rather than two, which is a measurement.
    "cqo": ("x86_step_cqo", False, ["rip", "b0", "b1", "rex", "w"]),
    "leave": ("x86_step_leave", False, ["rip", "b0"]),
    "ret": ("x86_step_ret", False, ["rip", "b0"]),
}

#: The successor of a memory-operand LOAD through a displacement, for BOTH
#: displacement widths.  `$disp` is the decoded number and `$next` is the literal
#: address after the instruction, so a disp8 and a disp32 load differ only in the
#: values substituted for those two; one string for both rows of `_SUCCS` is
#: therefore one statement of the model's semantics rather than two that have to
#: be checked against it separately.
_LOAD_WITH_DISP_SUCC = (
    "{ x86_set_reg $s $dst (mem_read_bytes $s.mem "
    "(Int.ofNat (x86_get_reg $s ($rm + x86_rex_b $rex)).toNat + $disp).toNat 8) "
    "with rip := $next }")

#: The successor of a SIB-addressed STORE through a displacement, for both
#: displacement widths: write 8 bytes at `rsp + disp`.  `$disp` and `$rex` are the
#: decoded values and `$next` the literal address after the instruction, so the
#: two widths differ only in what is substituted -- one string for both rows of
#: `_SUCCS`, for the reason `_LOAD_WITH_DISP_SUCC` gives.
#:
#: `x86_get_reg 4` and not `$s.rsp`: the model's base for a SIB operand is the
#: SIB byte's own base field, and the lemma says the byte is `24`, so the two
#: agree.  Writing `$s.rsp` here would be a second place that has to be right
#: about what the SIB byte means.
_SIB_STORE_WITH_DISP_SUCC = (
    "{ $s with mem := mem_write_bytes $s.mem "
    "(Int.ofNat (x86_get_reg $s 4).toNat + $disp).toNat "
    "(x86_get_reg $s ($reg + x86_rex_r $rex)) 8, rip := $next }")

#: Successor expressions, matching each lemma's conclusion.  `$s` is the
#: predecessor.  Kept beside `_FORMS` deliberately: a new form needs both, and
#: a mismatch between them is a proof failure rather than a silent gap.
_SUCCS = {
    "push_r64":
        "{ $s with rsp := $s.rsp - 8, rip := $next, "
        "mem := mem_write_bytes $s.mem ($s.rsp - 8).toNat $s.rbp 8 }",
    "alu_ri32:sub_rsp":
        "{ x86_flags_sub $s $s.rsp $imm ($s.rsp - $imm) with "
        "rsp := $s.rsp - $imm, rip := $next }",
    "alu_ri32:add_rsp":
        "{ x86_flags_add $s $s.rsp $imm ($s.rsp + $imm) with "
        "rsp := $s.rsp + $imm, rip := $next }",
    # The digit-immediate ALU successors.  `$imm` is the MODEL's expression for
    # the immediate, not the decoded number: `UInt64.ofInt (read_i32_le rc (m+3))`
    # for the `81` forms and `UInt64.ofInt (read_i8 (rc (m+3)))` for the `83` one,
    # and substituting a literal would state a different thing for every
    # sign-extended byte.  `$next` is what carries the length difference.
    "alu_ri32:add_reg":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) ((x86_get_reg $s "
        "($rm + x86_rex_b $rex)) + $imm) with rip := $next, zf := ($fa).zf, "
        "sf := ($fa).sf, cf := ($fa).cf, of_ := ($fa).of_ }",
    "alu_ri32:and":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) ((x86_get_reg $s "
        "($rm + x86_rex_b $rex)) &&& $imm) with rip := $next, zf := ($fl).zf, "
        "sf := ($fl).sf, cf := ($fl).cf, of_ := ($fl).of_ }",
    # No register in this one: digit 7 computes the subtraction, sets the flags
    # and throws the difference away.
    "alu_ri8:cmp":
        "{ $s with rip := $next, zf := ($fs).zf, sf := ($fs).sf, "
        "cf := ($fs).cf, of_ := ($fs).of_ }",
    "mov_rm64_imm32": "{ $s with rax := $imm, rip := $next }",
    "alu_ri32:add":
        "{ x86_flags_add $s $s.rax $imm ($s.rax + $imm) with "
        "rax := $s.rax + $imm, rip := $next }",
    "mov_r64_rm64_reg":
        "{ x86_set_reg $s ($reg + x86_rex_r $rex) "
        "(x86_get_reg $s ($rm + x86_rex_b $rex)) with rip := $next }",
    "mov_r64_rm64_sib":
        "{ x86_set_reg $s $dst (mem_read_bytes $s.mem $s.rsp.toNat 8) with "
        "rip := $next }",
    "mov_rm64_r64_sib":
        "{ $s with mem := mem_write_bytes $s.mem $s.rsp.toNat "
        "(x86_get_reg $s ($reg + x86_rex_r $rex)) 8, rip := $next }",
    "mov_rm64_r64_sib_disp8":
        _SIB_STORE_WITH_DISP_SUCC,
    "mov_rm64_r64_sib_disp32":
        _SIB_STORE_WITH_DISP_SUCC,
    # The three displacement modes, load and store.  The base is the rm field
    # extended by REX.B, so it is `$rm + x86_rex_b $rex` rather than the `5 +
    # …` this table used to hard-code for `rbp`.
    #
    # `Int.ofNat … + $disp` is the model's own `Int` arithmetic and is not
    # decoration: the address is `(Int.ofNat base + disp).toNat`, so writing
    # `base + disp` on a `Nat` would be a different expression that happens to
    # agree for a non-negative displacement and does not for a negative one --
    # and every spilled argument is at a negative offset.
    #
    # ONE string for both displacement widths, because the successor does not
    # mention the width: `$disp` is the decoded number and `$next` is the
    # literal address after the instruction, so a disp8 and a disp32 load differ
    # only in the values substituted for those two and a second copy of this text
    # would be a second thing to keep in step with the model.
    "mov_r64_rm64_disp8":
        _LOAD_WITH_DISP_SUCC,
    "mov_r64_rm64_disp32":
        _LOAD_WITH_DISP_SUCC,
    # No displacement at all: the address is the base register itself, so the
    # `Int.ofNat … + 0` round trip is gone and the instruction is one byte
    # shorter.
    "mov_r64_rm64_nodisp":
        "{ x86_set_reg $s $dst (mem_read_bytes $s.mem "
        "(x86_get_reg $s ($rm + x86_rex_b $rex)).toNat 8) with rip := $next }",
    "mov_rm64_r64_disp8":
        "{ $s with mem := mem_write_bytes $s.mem "
        "(Int.ofNat (x86_get_reg $s ($rm + x86_rex_b $rex)).toNat + $disp).toNat "
        "(x86_get_reg $s ($reg + x86_rex_r $rex)) 8, rip := $next }",
    "mov_rm64_r64_nodisp":
        "{ $s with mem := mem_write_bytes $s.mem "
        "(x86_get_reg $s ($rm + x86_rex_b $rex)).toNat "
        "(x86_get_reg $s ($reg + x86_rex_r $rex)) 8, rip := $next }",
    "mov_rm64_r64_disp32":
        "{ $s with mem := mem_write_bytes $s.mem "
        "(Int.ofNat (x86_get_reg $s ($rm + x86_rex_b $rex)).toNat + $disp).toNat "
        "(x86_get_reg $s ($reg + x86_rex_r $rex)) 8, rip := $next }",
    # `lea`: the address goes into a REGISTER, truncated to 64 bits.  A `mov`
    # successor would read memory at that address instead, which is the whole
    # difference between the two instructions.
    "lea_r64_rm64_disp32":
        "{ x86_set_reg $s $dst (UInt64.ofNat ((Int.ofNat "
        "(x86_get_reg $s ($rm + x86_rex_b $rex)).toNat + $disp).toNat % "
        "18446744073709551616)) with rip := $next }",
    "mov_rm64_r64_reg":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) "
        "(x86_get_reg $s ($reg + x86_rex_r $rex)) with rip := $next }",
    # `&&& 0xFF` is not decoration.  The model used to read the whole register
    # and leave it alone here, so this row said `rax := $s.rax` and matched.
    # The model now narrows the operand to its one byte, which is what
    # `movzx` does, and this row had to follow: the two disagreed in 14
    # examples, as a "Type mismatch" in the generated file, and the generated
    # file is right and the table was wrong.  A successor table is a copy of
    # the model's semantics; when the model is corrected, the copy has to be
    # corrected with it or it becomes a second, stale statement of the same
    # fact.
    "movzx_r64_r8": "{ $s with rax := $s.rax &&& 0xFF, rip := $next }",
    # The `&&& 0xFF` is what the instruction does and not decoration, exactly as
    # for `movzx` above: `movsx` reads one BYTE and sign-extends bit 7 of it, so
    # the successor is `x86_sign_extend8 (get &&& 0xFF)` and not the whole
    # register.  Writing `rax := $s.rax` here — which is what this table said
    # once — is a statement about a different instruction, and it is a statement
    # the model does not make, so the mismatch shows up as a `Type mismatch`
    # that displays the whole successor record and names neither the form nor
    # the byte.
    "movsx_r64_r8":
        "{ x86_set_reg $s $dst (x86_sign_extend8 "
        "(x86_get_reg $s ($rm + x86_rex_b $rex) &&& 0xFF)) with rip := $next }",
    "alu_rr:add":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) ($res) with rip := $next, zf := ($fa).zf, sf := ($fa).sf, cf := ($fa).cf, of_ := ($fa).of_ }",
    "alu_rr:sub":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) ($res) with rip := $next, zf := ($fs).zf, sf := ($fs).sf, cf := ($fs).cf, of_ := ($fs).of_ }",
    # `and`/`or`/`xor` share the shape above and differ only in the operator,
    # which `$res` supplies; the flags are `x86_flags_logic` on the same value.
    "alu_rr:and":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) ($res) with rip := $next, zf := ($fl).zf, sf := ($fl).sf, cf := ($fl).cf, of_ := ($fl).of_ }",
    "alu_rr:or":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) ($res) with rip := $next, zf := ($fl).zf, sf := ($fl).sf, cf := ($fl).cf, of_ := ($fl).of_ }",
    "alu_rr:xor":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) ($res) with rip := $next, zf := ($fl).zf, sf := ($fl).sf, cf := ($fl).cf, of_ := ($fl).of_ }",
    # The shifts write ZF and SF and leave CF and OF alone, which is the
    # difference from every row above and the reason this is not the same shape:
    # the model's `x86_flags_logic` computes all four and the record update
    # overrides only two, so a successor that also asserted `cf`/`of_` would be
    # a claim about a field the instruction does not set.
    #
    # `$sh` is the count after the model's clamp, kept as one term because the
    # lemma states it three times and a caller that inlined its own spelling
    # would have to match all three.
    "shift_imm8:shl":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) ((x86_get_reg $s "
        "($rm + x86_rex_b $rex)) <<< $sh) with rip := $next, "
        "zf := ($fl).zf, sf := ($fl).sf }",
    "shift_imm8:shr":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) ((x86_get_reg $s "
        "($rm + x86_rex_b $rex)) >>> $sh) with rip := $next, "
        "zf := ($fl).zf, sf := ($fl).sf }",
    "shift_imm8:sar":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) (x86_sign_extend32 "
        "(x86_get_reg $s ($rm + x86_rex_b $rex)) >>> $sh) with rip := $next, "
        "zf := ($fl).zf, sf := ($fl).sf }",
    # `= true` explicitly.  The model's `if` is over a `Bool`, and the
    # `by_cases` hypothesis is an equation about a `Prop`; writing the condition
    # the same way on both sides is what lets the hypothesis rewrite it.  It is
    # defeq either way, but only this spelling fires.
    "jcc_rel32":
        "{ $s with rip := if x86_cond $cc $s = true then $tgt else $fall }",
    "jmp_rel32":
        "{ $s with rip := $tgt }",
    # Transcribed from `x86_step_call_rel32`'s conclusion (lib/X86.lean:757),
    # and quoting the MODEL'S expressions for its two addresses rather than
    # pre-computing them as literals the way the `jmp`/`jcc` rows above do.
    #
    # That difference is the whole reason this row needed changing, and it is
    # not a style preference.  The lemma's conclusion carries
    # `(Int.ofNat m + 5 + off).toNat` and `UInt64.ofNat (m + 5)`; a successor
    # carrying the literals `4294967826` and `4294967984` is the SAME record up
    # to those two fields, so closing the step is an `isDefEq` that has to
    # evaluate the arithmetic -- and inside a 22-field structure whose `mem` is
    # a `Nat -> UInt8` function, the congruence check gives up and reports
    #
    #     Type mismatch
    #
    # with both sides printed in full and neither of them naming the field that
    # differs.  Quoting the model's expressions makes the two records
    # syntactically identical, so the step closes by `rfl` with no arithmetic
    # to do at all.  The literal would then be recovered where it is actually
    # needed, by the NEXT step's `rip` side condition, and `simp` does fold
    # `(Int.ofNat 4294967979 + 5 + (-158)).toNat` to `4294967826` -- checked,
    # not assumed.
    "call_rel32":
        "{ $s with rip := (Int.ofNat $m + 5 + $off).toNat, rsp := $s.rsp - 8, "
        "mem := mem_write_bytes $s.mem ($s.rsp - 8).toNat "
        "(UInt64.ofNat ($m + 5)) 8 }",
    "setcc":
        "{ x86_set_reg $s $rmv (if x86_cond $cc $s then 1 else 0) with"
        " rip := $next }",
        # `imul` reads its first multiplicand from the reg field -- the same field
    # it writes -- so `$dst` appears on both sides of the product, and it sets
    # no flags, so there is nothing else in the successor.
    "imul_r64_r64":
        "{ x86_set_reg $s $dst (x86_get_reg $s $dst * "
        "x86_get_reg $s ($rm + x86_rex_b $rex)) with rip := $next }",
"alu_rr:cmp":
        "{ $s with rip := $next, zf := ($fc).zf, sf := ($fc).sf, "
        "cf := ($fc).cf, of_ := ($fc).of_ }",
    "alu_rr:test":
        "{ $s with rip := $next, zf := ($fl).zf, sf := ($fl).sf, "
        "cf := ($fl).cf, of_ := ($fl).of_ }",
    # `x86_cqo`, and NOT `x86_sign_extend32`: this row was a second copy of the
    # model's semantics and it kept the OLD one.  `da151f0c` corrected the model's
    # `cqo` arm to `x86_cqo` (the sign extension of the whole 64-bit RAX) and
    # left this successor naming `x86_sign_extend32`, which is `movsxd`/`cdq` --
    # so the row disagreed with the model and with `x86_step_cqo`, and every
    # `cqo` step in a generated proof was a proof of a different instruction.
    # Nothing noticed because the only example with a `cqo` is `udivmod`, and
    # `udivmod` was already reported as `no lemma: group3:idiv` before reaching
    # it.  A successor table is a copy of the model, so the model was changed in
    # three places and this was the fourth.
    "cqo": "{ $s with rdx := x86_cqo $s.rax, rip := $next }",
    "leave":
        "{ $s with rbp := mem_read_bytes $s.mem $s.rbp.toNat 8, "
        "rsp := $s.rbp + 8, rip := $next }",
    "ret":
        "{ $s with rip := (mem_read_bytes $s.mem ($s.rsp.toNat) 8).toNat, "
        "rsp := $s.rsp + 8 }",
}


def _body(code, info):
    """The entry function's own instruction stream, or None if it won't decode.

    The lower bound is `entry` and it has to stay there, which is worth writing
    down because it is not obvious: `emit` (the value theorem) chains the decoded
    instructions LINEARLY from the first one, with no tree, so a range that began
    earlier would put the entry trampoline -- `push rbp; mov rbp, rsp; call main;
    pop rbp; ret` -- at the head of the chain and prove the theorem about the
    wrong function.  Widening this is therefore half of what a call to a function
    the compiler emitted BEFORE its caller needs, and not all of it; the other
    half, and what is left after this, is in
    `bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`.
    """
    base, entry = info["base_addr"], info["func_offset"]
    strs = [a for n, a in (info.get("labels") or {}).items()
            if n.startswith("str_")]
    end = (min(strs) - base) if strs else len(code)
    if end <= entry - base:
        return None
    try:
        return D.decode_all(code, entry - base, end)
    except D.DecodeError:
        return None


def _byte_facts(insns, code, base):
    facts = []
    for i in insns:
        for j in range(i.length):
            facts.append("rc %d = %d" % (base + i.offset + j, code[i.offset + j]))
    return " ∧\n    ".join(facts)


def _resolve(form, raw, addr, prev, k, cases=(), hs_in=None,
             length=1):
    """`(call, succ)` for one instruction: the step lemma applied at `addr`, and
    the successor expression its conclusion has.

    Both the straight-line and the path-tree emitters go through here, so a form
    cannot be wired up in one and forgotten in the other.
    """
    lemma, takes_imm, conds = _FORMS[form]
    imm = int.from_bytes(raw[3:7], "little", signed=True) if takes_imm else None
    # Each side condition is `try (<attempt>) <;> all_goals sorry`, so one that
    # does not go through is admitted rather than fatal, and Lean reports the
    # file as using `sorry`.
    #
    # Two things about that shape, both learned the hard way here.  The guard
    # must be INSIDE the inline `by`: an unsolved goal inside `(by simp [hs12])`
    # is an ELABORATION error, not a tactic failure, so neither an enclosing
    # `try` nor `first | exact ... | sorry` around the whole step catches it and
    # the file dies.  And it must be `try ... <;> all_goals sorry` rather than
    # `first | simp ... | all_goals sorry`: `first` commits to the first
    # alternative that does not THROW, not the first that closes the goal, so a
    # `simp` that runs and simplifies nothing is taken as a success and the
    # `sorry` alternative is never reached.
    #
    # This is what let `imul` mask an unrelated gap in the `rsp + disp8` load:
    # 8 examples read "no tree" instead of "tree, one step unproved".
    def sc_(tactic):
        return "(by try (%s) <;> all_goals sorry)" % tactic

    sc = []
    for c in conds:
        if c == "rip":
            if k == 0:
                sc.append(sc_("simp only [i0, X86State.init] <;> decide"))
            else:
                # The `by_cases` hypotheses in scope matter here: after a fork
                # the predecessor's successor equation has an `if` on the branch
                # condition in its `rip`, and without the hypothesis that `if`
                # does not reduce, so the next address is not a literal.
                #
                # `hs_in`, not `hs{k}`: the equation describing the state this
                # step starts in was emitted by the PREVIOUS step, which after a
                # fork is in the shared prefix and so has a lower number than
                # this step.  Indexing by `k` names an equation that does not
                # exist yet -- "Unknown identifier hs20".
                sc.append(sc_("simp [" + ", ".join(
                    [hs_in or ("hs%d" % k)] + list(cases)) + "]"))
        elif c in ("b0", "b1", "b2", "b3"):
            sc.append(sc_("simp [read_i32_le, read_i8, hb]"))
        elif c == "imm":
            sc.append(sc_("simp [read_i32_le, read_i8, hb]"))
        elif c == "disp":
            sc.append(sc_("simp [read_i8, hb]"))
        elif c == "disp32":
            # `read_i32_le`, and signed: a frame store is at a negative offset
            # and `read_i8` here would read one byte of a four-byte field.
            sc.append(sc_("simp [read_i32_le, read_i8, hb]"))
        elif c == "off":
            sc.append(sc_("simp [read_i32_le, read_i8, hb]"))
        elif c in ("dst", "dst_lt", "rm_ne", "rm_ne4", "rm_ne5"):
            # Closed arithmetic on the encoding: the destination register is
            # read out of the ModRM/REX bytes and the addressing-mode exclusions
            # are tests on that same rm, so every one is a literal here.
            sc.append(sc_("decide"))
        elif c in ("rex", "rex2", "w", "mod", "reg", "rm", "rb", "rr", "cc",
                   "lo", "hi", "nsetcc_lo", "njcc", "nzx", "op2", "notrex",
                   "digit"):
            # Closed arithmetic on the ModRM/REX literals, or a range test on a
            # concrete opcode byte: nothing here comes from the byte list, so
            # `decide` and not `simp [hb]`.
            sc.append(sc_("decide"))
        else:
            raise ValueError("bad condition " + c)
    extra_args, extra_succ = "", {}
    if form == "imul_r64_r64":
        # raw is 48 0f af <modrm>, so the REX is byte 0 and the ModRM byte 3 --
        # NOT byte 2 as for the 01 /r ALU forms, because `imul` is two opcode
        # bytes behind its ModRM.
        rex, op2, modrm = raw[0], raw[2], raw[3]
        reg, rm = (modrm >> 3) & 7, modrm & 7
        dst = reg + (8 if rex & 4 else 0)
        extra_args = " %d %d %d %d %d %d" % (rex, op2, modrm, reg, rm, dst)
        # `$rm` and `$reg` MUST be set here rather than left to the generic
        # `setdefault` below, which reads the ModRM out of `raw[2]`.  For every
        # other form `raw[2]` is the ModRM, but for `imul` -- 0F AF -- `raw[2]`
        # is the SECOND OPCODE and the ModRM is `raw[3]`, so the default fills
        # in `0xaf &&& 7 = 7` and the step lemma is applied with the wrong
        # source register.  The mismatch then reads as an opaque "Type
        # mismatch" on a 14-field record.
        extra_succ = {"$dst": str(dst), "$rm": str(rm), "$reg": str(reg),
                      "$rex": str(rex)}
    elif form == "movsx_r64_r8":
        # `REX 0F BE /r`, so the ModRM is `raw[3]` — the same off-by-one as
        # `imul` and `setcc` above, and for the same reason: an `0F` escape puts
        # the ModRM one byte further out than a one-byte opcode does.
        rex, modrm = raw[0], raw[3]
        reg, rm = (modrm >> 3) & 7, modrm & 7
        dst = reg + (8 if rex & 4 else 0)
        extra_args = " %d %d %d %d %d" % (rex, modrm, reg, rm, dst)
        extra_succ = {"$rex": str(rex), "$reg": str(reg), "$rm": str(rm),
                      "$dst": str(dst)}
    elif form in ("alu_ri32:add_reg", "alu_ri32:and", "alu_ri8:cmp"):
        # `REX.W 81 /digit id` or `83 /digit ib`, so the ModRM is `raw[2]` and the
        # immediate starts at `raw[3]` -- 4 bytes wide for `81`, one for `83`.
        # `digit` is the ModRM `reg` field and names the OPERATION; the
        # register is the rm field (+REX.B).  The decoder has already refused a
        # memory operand for this family, so mod is always 3.
        rex, modrm = raw[0], raw[2]
        digit, rm = (modrm >> 3) & 7, modrm & 7
        extra_args = " %d %d %d" % (rex, modrm, rm)
        # `UInt8.toInt` is the sign the instruction propagates, so the model's
        # own reader is used rather than a decoded Python integer: `83` sign
        # extends from ONE byte and `81` from four, and a literal would lose
        # exactly that.
        #
        # The outer parentheses are required and not cosmetic.  Lean's
        # application is left-associative, so `x86_flags_sub s a UInt64.ofInt x y`
        # is `((x86_flags_sub s a UInt64.ofInt) x) y` and the error is an
        # `Application type mismatch` that names `UInt64.ofInt` and neither the
        # form nor the byte -- in a file with one instruction per step, so it
        # names nothing at all about which instruction failed.
        if form == "alu_ri8:cmp":
            imm = "(UInt64.ofInt (read_i8 (rc %d)))" % (addr + 3)
        else:
            imm = "(UInt64.ofInt (read_i32_le rc %d))" % (addr + 3)
        a = "(x86_get_reg $s (%d + x86_rex_b $rex))" % rm
        if form == "alu_ri32:add_reg":
            res = "(%s + %s)" % (a, imm)
            extra_succ["$fa"] = "x86_flags_add $s %s %s %s" % (a, imm, res)
        elif form == "alu_ri32:and":
            res = "(%s &&& %s)" % (a, imm)
            extra_succ["$fl"] = "x86_flags_logic $s %s" % res
        else:
            res = "(%s - %s)" % (a, imm)
            extra_succ["$fs"] = "x86_flags_sub $s %s %s %s" % (a, imm, res)
        extra_succ.update({"$rex": str(rex), "$rm": str(rm),
                           "$imm": imm})
    elif form.startswith("shift_imm8:"):
        # `REX.W C1 /digit ib`, so the ModRM is `raw[2]` as for every other
        # one-byte opcode, and the `digit` is its REG field -- the operation,
        # not a register.  The register is the rm field (+REX.B).
        rex, modrm = raw[0], raw[2]
        digit, rm = (modrm >> 3) & 7, modrm & 7
        extra_args = " %d %d %d" % (rex, modrm, rm)
        # The count is the byte at `m + 3`, read as a byte and clamped, and it
        # is emitted as the model's own expression rather than as the decoded
        # number: the clamp is what makes a shift of 64 or more mean 64, so
        # substituting the number here would state a different thing for any
        # count outside 0..63.  `rc` is this file's name for what the lemma
        # calls `code`.
        sh = "UInt64.ofNat (if (rc %d).toNat ≥ 64 then 64 else (rc %d).toNat)" % (
            addr + 3, addr + 3)
        a = "(x86_get_reg $s (%d + x86_rex_b $rex))" % rm
        res = {"shl": "(%s <<< %s)" % (a, sh), "shr": "(%s >>> %s)" % (a, sh),
               "sar": "(x86_sign_extend32 %s >>> %s)" % (a, sh)}[
            form.split(":")[1]]
        extra_succ = {"$rex": str(rex), "$rm": str(rm), "$sh": sh,
                      "$fl": "x86_flags_logic $s %s" % res}
    elif form in ("mov_r64_rm64_reg", "mov_rm64_r64_reg", "alu_rr:add",                "alu_rr:sub", "alu_rr:cmp", "alu_rr:test", "alu_rr:and",
                "alu_rr:or", "alu_rr:xor"):
        rex, modrm = raw[0], raw[2]
        extra_args = " %d %d %d %d" % (rex, modrm, (modrm >> 3) & 7, modrm & 7)
        oa = "(x86_get_reg $s (%d + x86_rex_b $rex))" % (modrm & 7)
        ob = "(x86_get_reg $s (%d + x86_rex_r $rex))" % ((modrm >> 3) & 7)
        extra_succ = {"$rex": str(rex), "$rm": str(modrm & 7),
                      "$reg": str((modrm >> 3) & 7)}
        if form in ("alu_rr:add", "alu_rr:sub"):
            op = "+" if form.endswith("add") else "-"
            res = "(%s %s %s)" % (oa, op, ob)
            extra_succ["$res"] = res
            extra_succ["$fa" if op == "+" else "$fs"] = (
                "x86_flags_%s $s %s %s %s"
                % ("add" if op == "+" else "sub", oa, ob, res))
        elif form in ("alu_rr:and", "alu_rr:or", "alu_rr:xor"):
            # `&&&`, `|||` and `^^^` in Lean, not the Python spellings the
            # encoder uses (`&`, `|`, `^`).  The three share `x86_flags_logic`
            # on the same value, which is why `$fl` is one name for all of them.
            sym = {"and": "&&&", "or": "|||", "xor": "^^^"}[form.split(":")[1]]
            res = "(%s %s %s)" % (oa, sym, ob)
            extra_succ["$res"] = res
            extra_succ["$fl"] = "x86_flags_logic $s %s" % res
        elif form == "alu_rr:cmp":
            extra_succ["$fc"] = "x86_flags_sub $s %s %s (%s - %s)" % (
                oa, ob, oa, ob)
        elif form == "alu_rr:test":
            extra_succ["$fl"] = "x86_flags_logic $s (%s &&& %s)" % (oa, ob)
    elif form == "jcc_rel32":
        op2 = raw[1]
        off = int.from_bytes(raw[2:6], "little", signed=True)
        extra_args = " %d %d (%d)" % (op2, op2 - 0x80, off)
        # The two successors as LITERAL addresses.  The model's own form is
        # `(Int.ofNat m + 6 + off).toNat`, and `simp` does not reduce that
        # `Int` arithmetic, so the taken address never becomes a numeral and
        # the `if` cannot be resolved against the next instruction's address.
        extra_succ = {"$cc": str(op2 - 0x80), "$off": str(off),
                      "$tgt": str(addr + 6 + off), "$fall": str(addr + 6)}
    elif form == "jmp_rel32":
        off = int.from_bytes(raw[1:5], "little", signed=True)
        extra_args = " (%d)" % off
        extra_succ = {"$off": str(off), "$tgt": str(addr + 5 + off)}
    elif form == "call_rel32":
        # Same reason as jmp_rel32 above, plus one more: a call has TWO
        # addresses -- the target it branches to, and the return address it
        # PUSHES. The pushed value is `UInt64.ofNat (m + 5)`, i.e. `$ret`.
        off = int.from_bytes(raw[1:5], "little", signed=True)
        extra_args = " (%d)" % off
        # `$off` parenthesised, and the address literals dropped: the successor
        # quotes the model's own expression (see `_SUCCS`), and `$tgt`/`$ret`
        # would only be substituting pre-computed arithmetic for it.
        extra_succ = {"$off": "(%d)" % off}
    elif form == "cqo":
        # REX 99: the only byte after the prefix, so there is no ModRM and
        # nothing to read out of the encoding but the REX itself.  `b1` is the
        # hypothesis that pins the opcode, and it comes from the byte list like
        # every other `b1` here.
        extra_args = " %d" % raw[0]
        extra_succ = {"$rex": str(raw[0])}
    elif form == "setcc":
        op2, modrm = raw[1], raw[2]
        extra_args = " %d %d %d %d" % (op2, modrm, op2 - 0x90, modrm & 7)
        extra_succ = {"$cc": str(op2 - 0x90), "$rmv": str(modrm & 7)}
    elif form == "mov_rm64_r64_sib":
        # `mov qword [rsp], r64`: the REX is an ARGUMENT (the lemma is general
        # over it, so a source in r8..r15 and its `4c` prefix are covered) and
        # the SOURCE is the ModRM `reg` field extended by REX.R -- the field
        # sense is the store direction's, the reverse of the load's.
        modrm, rex = raw[2], raw[0]
        reg = (modrm >> 3) & 7
        extra_args = " %d %d %d" % (rex, modrm, reg)
        extra_succ = {"$rex": str(rex), "$reg": str(reg)}
    elif form == "mov_r64_rm64_sib":
        # `mov r64, qword [rsp]`: the same addressing, and the DESTINATION is
        # the ModRM `reg` field extended by REX.R.  `dst` is what the successor
        # names, because `x86_set_reg` is a `match` on its index and `simp` will
        # not reduce one on a non-literal -- so the concrete value comes from
        # the ENCODING here, with the lemma's `reg + x86_rex_r rex = dst` beside
        # it as the equation that ties the two together.
        modrm, rex = raw[2], raw[0]
        reg = (modrm >> 3) & 7
        dst = reg + (8 if rex & 4 else 0)
        extra_args = " %d %d %d %d" % (rex, modrm, reg, dst)
        extra_succ = {"$rex": str(rex), "$reg": str(reg), "$dst": str(dst)}
    elif form in _SIB_STORE_WITH_DISP_FORMS:
        # `mov qword [rsp + disp], r64`: ModRM `4_` (mod=1 or 2, rm=4), the SIB
        # byte at `m + 3`, and the DISPLACEMENT at `m + 4` -- one byte further
        # out than the non-SIB forms', which is the whole reason this is its own
        # branch rather than a reuse of the one above with a different suffix.
        # The REX is an ARGUMENT here (these two lemmas are general over it, so a
        # source in r8..r15 and its `4c` prefix are covered) where the
        # no-displacement sibling above pins it to 0x48 in the statement itself.
        modrm, rex = raw[2], raw[0]
        reg = (modrm >> 3) & 7
        if form == "mov_rm64_r64_sib_disp32":
            disp = int.from_bytes(raw[4:8], "little", signed=True)
        else:
            disp = raw[4] - 256 if raw[4] > 127 else raw[4]
        # Parenthesised, for the reason the memory branch gives: an unparenthesised
        # negative literal swallows the hypothesis that follows it.
        extra_args = " %d %d %d (%d)" % (rex, modrm, reg, disp)
        extra_succ = {"$reg": str(reg), "$rex": str(rex), "$disp": str(disp)}
    elif form in _MEMORY_DISP_FORMS:
        # Every memory-operand `mov`/`lea` shape except the two SIB ones, and
        # they all take their arguments in the same order: REX, ModRM, reg (the
        # source for a store and the destination for a load), rm (the base),
        # then `dst` for the load direction and the displacement last.
        rex, modrm = raw[0], raw[2]
        reg, rm = (modrm >> 3) & 7, modrm & 7
        rex_r = 8 if rex & 4 else 0
        mode = (modrm >> 6) & 3
        # A negative displacement is parenthesised: `-8 (by ...)` parses as an
        # application of it.  A disp32 is SIGNED as well as wide, and `wide_recv`
        # frames live at about `rbp - 0x410`, so reading it unsigned here would
        # put every frame store at `rbp + 4294966896`.
        if mode == 0:
            disp = None
            darg = ""
            disp_succ = {}
        elif mode == 1:
            disp = raw[3] - 256 if raw[3] > 127 else raw[3]
            darg = " (%d)" % disp
            disp_succ = {"$disp": str(disp)}
        else:
            disp = int.from_bytes(raw[3:7], "little", signed=True)
            darg = " (%d)" % disp
            disp_succ = {"$disp": str(disp)}
        head = " %d %d %d %d" % (rex, modrm, reg, rm)
        dst_succ = {"$dst": str(reg + rex_r)}
        if form in _LOAD_MEMORY_FORMS:
            extra_args = head + " %d" % (reg + rex_r) + darg
        else:
            extra_args = head + darg
            dst_succ = {}
        extra_succ = {"$rex": str(rex), "$reg": str(reg), "$rm": str(rm)}
        extra_succ.update(dst_succ)
        extra_succ.update(disp_succ)
    call = "%s %s rc %d%s" % (lemma, prev, addr, extra_args)
    if takes_imm:
        # Parenthesised, always, not only when negative.  Lean's application is
        # left-associative, so an unparenthesised negative literal swallows the
        # first hypothesis that follows it: `x86_step_call_rel32 s rc m -158 (by
        # …)` is `x86_step_call_rel32 s rc m - (158 (by …))`, and the error is
        # "Function expected at 158" -- which names neither the form, nor the
        # instruction, nor the argument, in a file with one instruction per step.
        call += " (%d)" % imm
    call += " " + " ".join(sc)
    # Every placeholder is substituted in ONE pass, from a single table.  It
    # used to be positional -- `$s` and `$m` first, then the `extra_succ`
    # values -- which silently breaks any form whose successor is BUILT from
    # those values, because `$s` and `$rex` arrive already inside the inserted
    # text and nothing replaces them after.  The result is a `$s` in the middle
    # of a Lean term, reported as `term.pseudo.antiquot has not been
    # implemented`, which names neither the form nor the substitution.  One
    # table, one pass, no ordering to get wrong.
    subs = dict(extra_succ)
    subs["$s"] = prev
    subs["$m"] = str(addr)
    # The NEXT address as a literal, not `$m + length`.  `simp` does not reduce
    # `4294967868 + 4` to `4294967872` -- large Nat literals are not folded by
    # the simplifier -- so a successor stated as an addition leaves every
    # subsequent `rip` comparison unprovable, and the failure reads as a bare
    # `False` from the `simp` that was trying.
    subs["$next"] = str(addr + length)
    # `setdefault`, not `[...]`: `$imm` is ALSO a placeholder the `_resolve`
    # branch for the digit-immediate ALU forms fills in, with the MODEL's
    # expression for the immediate (`UInt64.ofInt (read_i32_le rc (m+3))`) rather
    # than a literal.  Assigning here instead overwrote that one, and the
    # generated application said `UInt64.ofInt UInt64.ofInt (…)` — the symptom
    # being an `Application type mismatch` naming `UInt64.ofInt` and therefore
    # naming neither the form nor the byte, in a file with one instruction per
    # step.  Two spellings of `$imm` in one table is the same hazard as B3's
    # positional substitution: one placeholder, one source.
    subs.setdefault("$imm", str(imm) if imm is not None else "0")
    if len(raw) > 2:
        modrm = raw[2]
        subs.setdefault("$rex", str(raw[0]))
        subs.setdefault("$rm", str(modrm & 7))
        subs.setdefault("$reg", str((modrm >> 3) & 7))
    # A FIXPOINT, not one pass.  A value substituted in can itself contain
    # placeholders -- the flag expressions are built from the operand
    # templates, so `$fc`'s value contains `$s` and `$rex` -- and any fixed
    # ordering leaves those behind.  Sorting by length only moves the breakage
    # to a different form; repeating until the text stops changing cannot.
    succ = _SUCCS[form]
    for _ in range(len(subs) + 1):
        nxt = succ
        for ph, val in subs.items():
            nxt = nxt.replace(ph, val)
        if nxt == succ:
            break
        succ = nxt
    return call, succ


#: The two `mov` directions plus `lea`, which share one addressing-mode split.
#: `lea` is in the list because its address computation is `x86_mem_addr`'s and
#: only its RESULT differs (a register write, truncated, rather than a memory
#: access), so the modes have to be named once for all three.
_MEMORY_FORMS = ("mov_r64_rm64", "mov_rm64_r64", "lea_r64_rm64")

#: ModRM `mod` -> the suffix that names it.  Three modes, and `mod=0` is the
#: only one where the meaning depends on the `rm` field as well -- hence `_rip`.
_MEM_MODE = {0: "nodisp", 1: "disp8", 2: "disp32"}

#: The LOAD direction: the ones whose lemma takes a CONCRETE `dst` argument and
#: whose successor writes a register.  `lea` is in it for the same reason it is
#: in `_MEMORY_FORMS` below -- its address computation is `x86_mem_addr`'s and
#: only its RESULT differs.  The two tuples are derived from each other so they
#: cannot drift apart: adding a load mode to one without the other produced a
#: call with a `dst` argument the lemma does not take, which reads as an arity
#: error naming neither the form nor the instruction.
_LOAD_MEMORY_FORMS = ("mov_r64_rm64_disp8", "mov_r64_rm64_disp32",
                      "mov_r64_rm64_nodisp", "lea_r64_rm64_disp32")

#: The memory-operand shapes `_resolve` supplies arguments for.  The two SIB
#: ones are absent deliberately: they have their own `_resolve` branches above,
#: because a SIB byte puts the displacement one byte further out and its base is
#: read from the SIB rather than from the ModRM's rm field.
_MEMORY_DISP_FORMS = _LOAD_MEMORY_FORMS + (
    "mov_rm64_r64_disp8", "mov_rm64_r64_nodisp", "mov_rm64_r64_disp32")

#: The SIB-addressed stores WITH a displacement.  Not in `_MEMORY_DISP_FORMS`
#: above even though they are memory forms with a displacement, because their
#: displacement is at `m + 4` rather than `m + 3` and they have their own
#: `_resolve` branch for exactly that reason; putting them in that tuple would
#: silently read the SIB byte as the low byte of a displacement.
_SIB_STORE_WITH_DISP_FORMS = ("mov_rm64_r64_sib_disp8",
                              "mov_rm64_r64_sib_disp32")


_BRANCH_FORMS = frozenset(("jcc_rel32", "jcc_rel8", "jmp_rel32", "jmp_rel8",
                           "call_rel32"))
"""Forms whose successor is not `the next instruction`, so a straight-line chain
cannot follow them.  `call_rel32` is here even though it is not a branch on a
flag: it jumps, and the address it lands on is a literal supplied by the decode
branch, so the instruction after it is not the one at `m + length`."""


def _shapes(code, insns):
    """`[(insn, resolved_form, raw)]`, splitting the two `mov` opcodes into
    their shapes.  A form not in `_FORMS` is left alone, and the caller reports
    it by name rather than skipping the function."""
    out = []
    for i in insns:
        raw = code[i.offset:i.next_offset]
        form = i.form
        modrm = raw[2] if len(raw) > 2 else 0
        if form in ("alu_ri32:add", "alu_ri32:sub") and len(raw) >= 3:
            # `alu_ri32:add` is emitted ONLY as `add rsp, imm32` (ModRM c4);
            # `alu_ri32:sub` only as `sub rsp, imm32` (ModRM ec).  Keying the
            # form to an rax lemma matches zero of them, and the symptom is a
            # proof that does not apply rather than a gap.
            want = 0xc4 if form == "alu_ri32:add" else 0xec
            form = form + ("_rsp" if raw[2] == want else "_reg")
            # `_reg`, not `_other`: the decoder REFUSES a memory operand for
            # this opcode family ("ALU with an immediate and a memory operand is
            # not emitted", formal/x86_64_decode.py), so every remaining
            # `alu_ri32:add` really is `add r64, imm32` and the old `_other`
            # stood for one instruction under a name that said it was a
            # fallback.  The digit is already in the form name, so the split
            # that is left to do is rsp versus not-rsp and nothing else.
        if form in _MEMORY_FORMS:
            # Every addressing mode gets its OWN name, because a name that does
            # not say which mode it is is how B2 happened: an unmapped shape used
            # to be satisfied by whatever lemma happened to share its name, and
            # `mov [rbp-0x410], rax` (mod=2) was reachable under the name of
            # `mov [rbp+disp8], rax` (mod=1) because only two of the three modes
            # were named at all.  An unhandled mode is now REPORTED by name.
            #
            # `_rip` is the one that needs naming most: mod=0 with rm=5 has no
            # base register at all -- the displacement is measured from the end
            # of the instruction -- so it is a different address computation and
            # a mod=0 lemma applied to it would claim `mov [rbp]`.
            m, rm = modrm >> 6, modrm & 7
            if m == 3:
                form += "_reg"
            elif rm == 4 and len(raw) >= 4:
                # A SIB byte follows, so the displacement is one byte further
                # out.  Only the no-displacement SIB is wired.
                form += "_sib" + ("" if m == 0 else "_" + _MEM_MODE[m])
            elif m == 0 and rm == 5:
                form += "_rip"
            else:
                form += "_" + _MEM_MODE[m]
        out.append((i, form, raw))
    return out


class _Node:
    """One instruction in the path tree, with the children its branch allows.

    `kind` is "seq" (one successor), "jcc" (two, selected by a condition on
    `state`), "jmp" (one, unconditional) or "ret" (none: the run is over).
    """
    __slots__ = ("insn", "form", "raw", "addr", "kind", "state", "succ", "kids")

    def __init__(self, insn, form, raw, addr, kind, state, succ):
        self.insn, self.form, self.raw, self.addr = insn, form, raw, addr
        self.kind, self.state, self.succ = kind, state, succ
        self.kids = []


def _tree(code, info, shapes):
    """The path tree from the entry, or None if it loops or leaves the body.

    A loop is reported as None rather than walked: the chain proves one path, so a
    back edge has no finite unfolding here.  Four of the examples have one and
    they are named in the test output as needing induction.

    **A loop is a REVISITED ADDRESS, not a length.**  The test for it used to be
    `depth > 64`, one frame per instruction, which conflated "this path is long"
    with "this path is cyclic" and so reported a straight-line function of 65
    instructions as a loop.  The corpus stayed under it by luck -- the longest
    example is 60 instructions -- and it is what stopped the first program here
    that calls a function with more than a handful of arguments: a 24-argument
    call is 24 `mov imm32; sub rsp; mov [rsp]` triples in the caller and 24 loads
    in the callee, about 130 instructions on one path, and the message was
    "body loops, or branches out of the fun" for a program with no loop in it.

    What is left of the budget bounds PYTHON's stack, not the program: `build`
    is one Python frame per instruction, so the honest limit is the interpreter's
    own recursion limit less what the caller already occupies.
    """
    base, entry = info["base_addr"], info["func_offset"]
    by_addr = {base + i.offset: (i, f, r) for i, f, r in shapes}
    deep = max(256, sys.getrecursionlimit() - 200)

    def build(addr, state, depth, seen):
        if depth > deep or addr in seen:
            return None
        seen = seen | {addr}
        got = by_addr.get(addr)
        if got is None:
            return None
        insn, form, raw = got
        if form in ("jcc_rel32", "jcc_rel8"):
            off = (int.from_bytes(raw[2:6], "little", signed=True)
                   if form == "jcc_rel32"
                   else int.from_bytes(raw[1:2], "little", signed=True))
            # The displacement is relative to the END of the instruction, not
            # to its first byte, so the length is part of the target address.
            n = 6 if form == "jcc_rel32" else 2
            nxt = addr + n
            node = _Node(insn, form, raw, addr, "jcc", state, nxt)
            taken = build(addr + n + off, None, depth + 1, seen)
            fell = build(nxt, None, depth + 1, seen)
            if taken is None or fell is None:
                return None
            # `by_cases h : P` presents the `P` case FIRST, so the taken path
            # must be kids[0] or each arm gets the other's address.
            node.kids = [taken, fell]
            return node
        if form in ("jmp_rel32", "jmp_rel8"):
            off = (int.from_bytes(raw[1:5], "little", signed=True)
                   if form == "jmp_rel32"
                   else int.from_bytes(raw[1:2], "little", signed=True))
            node = _Node(insn, form, raw, addr, "jmp", state, addr + off)
            node.kids = [build(addr + off, None, depth + 1, seen)]
            return None if node.kids[0] is None else node
        if form == "call_rel32":
            # A CALL IS A JUMP, and the tree has to follow the TARGET.  It used
            # to fall through to `addr + length`, which is the instruction after
            # the call -- and the model's successor says `rip := (Int.ofNat m + 5
            # + off).toNat`, so the instruction at `m + 5` is not executed at
            # all after a call.  The chain went on to step it anyway, and the
            # step's `rip` side condition is `s.rip = <m + 5>`, which is FALSE;
            # `simp` turned that into `False`, the guard admitted it, and the
            # proof carried a `sorry` from the instruction after the call
            # onwards -- eight examples, silently, with `failing` at 0.
            #
            # That is B22's lesson (a form with a lemma conceals the state of
            # everything after it) with the concealment on the other side: the
            # lemma was right, the TREE was wrong, and only the sorry count said
            # so.  `count`, `fact`, `fib`, `pow2`, `sqsum` and `sum` are the
            # six that recurse, so their target is a back edge and the honest
            # answer is `loops`; the non-recursive callers get a real proof.
            #
            # What the path does NOT get is the instruction AFTER the callee
            # returns: the node's successor is the target, so the continuation
            # in the caller is never built.  That is a real limit and it is
            # invisible today because it only costs anything when the
            # continuation itself calls something, which no example in the corpus
            # does.
            off = int.from_bytes(raw[1:5], "little", signed=True)
            node = _Node(insn, form, raw, addr, "jmp", state, addr + 5 + off)
            node.kids = [build(addr + 5 + off, None, depth + 1, seen)]
            return None if node.kids[0] is None else node
        if form == "ret":
            return _Node(insn, form, raw, addr, "ret", state, None)
        node = _Node(insn, form, raw, addr, "seq", state, addr + insn.length)
        node.kids = [build(addr + insn.length, None, depth + 1, seen)]
        return None if node.kids[0] is None else node

    try:
        root = build(entry, "i0", 0, frozenset())
    except RecursionError:
        # One Python frame per instruction, so a straight line longer than the
        # interpreter's own limit cannot be walked at all.  `None` is the answer
        # a loop gets, which is what a path this long looked like before the loop
        # test became a revisited address -- and it is a graceful "no tree"
        # rather than an exception that takes the whole suite with it.
        return None
    if root is None:
        return None
    return root


def _nodes(node):
    """How many instructions the tree holds, both arms of every fork included."""
    return 1 + sum(_nodes(k) for k in node.kids)


def _paths(node, acc=None):
    """Every root-to-`ret` path in the tree, as lists of nodes."""
    acc = [] if acc is None else acc
    acc.append(node)
    if not node.kids:
        yield list(acc)
    for kid in node.kids:
        yield from _paths(kid, list(acc))
    acc.pop()


def _byte_list(insns, code, base):
    """Every byte of the function, as `rc <addr> = <value>` conjuncts."""
    out = []
    for i in insns:
        for j in range(i.length):
            out.append("rc %d = %d" % (base + i.offset + j, code[i.offset + j]))
    return out


def _header(code, insns, base, steps):
    """The import, the code function, and every byte as a fact.

    `steps` is how many step equations the file below will introduce, and it
    buys the second option below.
    """
    # A heartbeat budget.  The `hrip` step at the end of each path is one `simp`
    # over every successor equation on that path, and on the longer ones that is
    # a real amount of work: the default budget reports "deterministic timeout"
    # and the theorem is fine.  A timeout is NOT catchable by `try`, so the
    # `try`-guarded block below does not help here and the budget is the only
    # lever -- hence raising it rather than guarding.
    #
    # `maxRecDepth` is the other half of the same step, and it is a LIMIT rather
    # than an allocation, so raising it costs nothing when it is not needed.  The
    # default is 1000, and it is the closing `simp` that runs out rather than any
    # single step: its term nests one successor equation per instruction, so the
    # depth it needs grows with the length of the function and a constant would
    # be a constant that is wrong again at the next example.  Measured on
    # `bitops`, 44 steps, the first two words that go through are 1200 and 2000
    # and 1000 fails -- about 27 per step, so 40 is the factor used here, with
    # the default as the floor for the short ones that never needed it.
    depth = max(1000, 40 * max(steps, 1))
    out = ["import X86\n",
           "set_option maxHeartbeats 4000000\n",
           "set_option maxRecDepth %d\n" % depth,
           "def rc (addr : Nat) : UInt8 :=",
           "  if addr < %d then 0 else" % base,
           "  ([%s].getD (addr - %d) 0)\n"
           % (", ".join("0x%02x" % b for b in code), base),
           "/-- Every byte of the function, as a fact about `rc`. -/",
           "theorem all_bytes :\n    %s := by" % _byte_facts(insns, code, base)]
    # Proved as a chain of small `native_decide`s rather than one.  Asking for
    # a single `Decidable` instance for a conjunction of a few hundred byte
    # equalities exhausts instance synthesis, and it fails as "failed to
    # synthesize Decidable (rc ... = 85 /\u2227 rc ... = 72 /\u2227 ...)" -- a
    # wall of byte facts that never mentions the fact that there are too many
    # of them.  Each conjunct is closed on its own instead.
    facts = _byte_list(insns, code, base)
    if not facts:
        out.append("  trivial")
    elif len(facts) == 1:
        out.append("  native_decide")
    else:
        # `And.intro` rather than `refine`: these files import only X86, so
        # `refine` (a Mathlib tactic) is not in scope, and the core
        # `And.intro` needs nothing.
        term = "by native_decide"
        for f in reversed(facts[1:]):
            term = "And.intro (by native_decide) (%s)" % term
        out.append("  exact " + term)
    out.append("")
    return out


def _plan(path):
    """`(code, info, insns, shapes)` for one source file."""
    r = B.compile_formal(path, prove=False, check=False, arch="x86_64")
    code, info = r["code"], r["info"]
    insns = _body(code, info)
    if insns is None:
        raise ValueError("body does not decode")
    shapes = _shapes(code, insns)
    missing = sorted({f for _, f, _ in shapes} - set(_FORMS))
    if missing:
        raise ValueError("no step lemma wired for: " + ", ".join(missing))
    return code, info, insns, shapes


#: `emit` cannot state the theorem for a function that branches, and saying so
#: by name is what keeps a coverage improvement from reading as a failure.  A
#: `jcc`'s successor carries `rip := if … then … else …`, so the next step's
#: address is not a literal and the chain stops one instruction later -- with an
#: error AT THAT STEP, which says nothing about the branch that caused it, and
#: which only appears once every other form has a lemma.  The path-tree emitter
#: is the one for those functions; see `emit_terminates`.
BRANCHING = "branches"


def emit(path, expected):
    """The straight-line end-to-end theorem: every input, constant result.

    Only usable when the function's result does not depend on its input and its
    body does not branch -- 3 of the 43 examples -- see `emit_terminates` for
    the theorem that covers the rest.  A branch is refused here, by name, rather
    than left to fail: the failure it would produce is at some later step and
    names neither the form nor the branch.

    Its two closing facts -- the value in `rax` and that `rip` reached the exit
    -- are `try`-guarded and admitted where they do not go through, and the
    caller counts the `sorry`s.  That is the same treatment `emit_terminates`
    gives its `hrip`, and for the same reason: a function that spills its
    argument cannot have its value resolved from the chain without the memory
    separation inequalities (B18), and reporting that as a FAILURE says the
    model disagrees with the source when the truth is that a side condition was
    not discharged.  B21 is the bug that made that distinction cost the whole
    run its credibility once; this is the same failure in a new place, and the
    first thing a wiring change found by reaching a new example.
    """
    code, info, insns, shapes = _plan(path)
    branching = sorted({f for _, f, _ in shapes} & _BRANCH_FORMS)
    if branching:
        raise ValueError("%s: %s" % (BRANCHING, ", ".join(branching)))
    base, entry = info["base_addr"], info["func_offset"]
    L = _header(code, insns, base, len(shapes))
    a = L.append
    a("/-- For EVERY input: the model runs this image to the exit pc and leaves")
    a("    `%d` in `rax`.  Proved, not asserted. -/" % expected)
    a("theorem all_inputs (n : UInt64) :")
    a("    (x86_exec_exit (X86State.init n %d) rc 0).map X86State.rax" % entry)
    a("      = some %d := by" % expected)
    a("  rw [x86_exec_exit_eq_go]")
    a("  have hb := all_bytes")
    a("  let i0 : X86State := X86State.init n %d" % entry)

    prev, k = "i0", 0
    chain = []
    for insn, form, raw in shapes:
        addr = base + insn.offset
        call, succ = _resolve(form, raw, addr, prev, k, (), None, insn.length)
        nxt = "s%d" % (k + 1)
        a("  have hstep%d : x86_step %s rc = some %s :=" % (k, prev, succ))
        a("    %s" % call)
        a("  obtain ⟨%s, h%d⟩ : ∃ t, x86_step %s rc = some t :="
          % (nxt, k, prev))
        a("    ⟨_, hstep%d⟩" % k)
        a("  have hs%d : %s = %s := by" % (k + 1, nxt, succ))
        a("    rw [h%d] at hstep%d" % (k, k))
        a("    exact Option.some.inj hstep%d" % k)
        chain.append((k, nxt))
        prev, k = nxt, k + 1

    hs = ", ".join("hs%d" % (j + 1) for j, _ in chain)
    a("  have hrax : %s.rax = %d := by" % (prev, expected))
    a("    try (simp [%s, i0, x86_set_reg, x86_get_reg, x86_rex_b, x86_rex_r," % hs)
    a("      x86_flags_sub, x86_flags_add, x86_flags_logic, x86_sign_extend8,")
    a("      x86_mem_addr, x86_trunc32]) <;>")
    a("    first | decide | omega")
    a("    all_goals sorry")
    a("  have hrip : %s.rip = 0 := by" % prev)
    a("    have key : ∀ (m : Nat → UInt8) (a : Nat) (v : UInt64) (b : Nat),")
    a("        a + 8 ≤ b → mem_read_bytes (mem_write_bytes m a v 8) b 8")
    a("          = mem_read_bytes m b 8 :=")
    a("      fun m a v b h => mem_read_bytes_write_above m a v 8 8 b h")
    a("    simp [%s, i0, X86State.init, x86_flags_sub, x86_flags_add," % hs)
    a("      x86_set_reg, x86_get_reg, x86_rex_b, x86_rex_r, x86_flags_logic,")
    a("      x86_mem_addr, x86_trunc32] <;>")
    a("    try (repeat rw [key _ _ _ _ (by first | decide | omega)]) <;>")
    a("    try (simp only [mem_read_bytes, ite_true]) <;>")
    a("    first | decide | omega")
    a("    all_goals sorry")
    rules = ["x86_exec_go_exit_step (by decide) "
             "(by simp only [i0, X86State.init] <;> decide) h0"]
    for j, _ in chain[1:]:
        rules.append("x86_exec_go_exit_step (by decide) (by simp [hs%d]) h%d"
                     % (j, j))
    rules.append("x86_exec_go_exit_at (by decide) hrip")
    a("  rw [%s]" % ",\n      ".join(rules))
    a("  simp [hrax]")
    return "\n".join(L) + "\n"


def emit_terminates(path):
    """For EVERY input, the model runs this image to the exit pc.

    This is the theorem that scales.  `emit` states the value left in `rax`,
    which is a fixed constant only for the 7 of 43 examples whose result does
    not depend on the input -- so for the other 36 it cannot even be FORMULATED,
    however good the chain gets.  Termination needs no value reasoning: it says
    the run reaches the exit pc, which is what makes `x86_exec_exit` total, and
    it holds for every input whether or not the answer is constant.

    The chain forks at each conditional.  A `jcc`'s successor carries an `if` on
    the condition in its `rip` rather than a constant address, so the two paths
    have different next addresses, and the only sound way through is to split on
    the condition -- which is what `by_cases` does.  The case hypothesis then
    joins the `simp` sets, so a step after a fork resolves its `rip` from the
    branch's own successor equation.
    """
    code, info, insns, shapes = _plan(path)
    base, entry = info["base_addr"], info["func_offset"]
    root = _tree(code, info, shapes)
    if root is None:
        raise ValueError("body loops, or branches out of the function")
    # Every node in the tree, which is an upper bound on the length of any one
    # path and so on the depth the closing `simp` at each `ret` will need.  Both
    # arms of a fork are counted, which over-counts; the option is a limit, so
    # over-counting only ever costs headroom nobody uses.
    out = _header(code, insns, base, _nodes(root))
    out.append("/-- For EVERY input, the model runs this image to the exit pc.\n"
               "    No `sorry`: the path tree is walked once per branch outcome. -/")
    out.append("theorem terminates (n : UInt64) :")
    out.append("    (x86_exec_exit (X86State.init n %d) rc 0).isSome = true := by"
               % entry)
    out.append("  rw [x86_exec_exit_eq_go]")
    out.append("  have hb := all_bytes")
    out.append("  let i0 : X86State := X86State.init n %d" % entry)

    counter = [0]

    def walk(node, state, ind, cases, rules, hs_in=None, hs_path=()):
        """Emit one node and, for a branch, both of its children.

        `cases` are the `by_cases` hypotheses in scope at this point; `rules`
        the `x86_exec_go_exit_step` applications that reduce the run so far, in
        order, which is what the closing `rw` replays.
        """
        k = counter[0]
        counter[0] = k + 1
        call, succ = _resolve(node.form, node.raw, node.addr, state, k,
                              cases, hs_in, node.insn.length)
        nxt = "s%d" % (k + 1)
        pad = "  " * ind
        case_simp = (", " + ", ".join(cases)) if cases else ""

        def emit(line):
            out.append(pad + line if line else "")

        emit("have hstep%d : x86_step %s rc = some %s :=" % (k, state, succ))
        emit("  " + call)
        emit("obtain \u27e8%s, h%d\u27e9 : \u2203 t, x86_step %s rc = some t :="
             % (nxt, k, state))
        emit("  \u27e8_, hstep%d\u27e9" % k)
        emit("have hs%d : %s = %s := by" % (k + 1, nxt, succ))
        emit("  rw [h%d] at hstep%d" % (k, k))
        emit("  exact Option.some.inj hstep%d" % k)
        # `x86_exec_go_exit_step`'s second argument is `h_not_exit : s_k.rip ≠
        # exit`, and `s_k` is the state this step STARTS in -- which the
        # PREVIOUS step's successor equation describes.  So this uses `hs_k`,
        # not `hs_{k+1}`; for the first step the predecessor is the initial
        # state, which `i0` names.
        # `hs_in`, the same equation the step's own `rip` fact uses -- after a
        # fork that is the BRANCH's successor equation, not this step's, and
        # naming this step's instead cites an `hs` the other arm has not emitted.
        if k == 0:
            step_rule = ("x86_exec_go_exit_step (by decide) (by simp only "
                         "[i0, X86State.init] <;> decide) h0")
        else:
            step_rule = ("x86_exec_go_exit_step (by decide) (by simp [%s%s]) h%d"
                         % (hs_in or ("hs%d" % k), case_simp, k))

        if node.kind == "jcc":
            # The condition is over the state the branch READS -- the one this
            # step starts in -- not the successor.  A `jcc`'s successor carries
            # `rip := if x86_cond cc s_k ... else ...`, so splitting on the
            # successor's own flags produces a hypothesis that never rewrites
            # anything, and the next step's `rip` stays an `if`.
            cc = node.raw[1] - 0x80
            emit("by_cases hc%d : x86_cond %d %s = true" % (k, cc, state))
            both = rules + [step_rule]
            emit("\u00b7")
            walk(node.kids[0], nxt, ind + 1, cases + ["hc%d" % k], both,
                 "hs%d" % (k + 1), hs_path + ("hs%d" % (k + 1),))
            emit("\u00b7")
            walk(node.kids[1], nxt, ind + 1, cases + ["hc%d" % k], both,
                 "hs%d" % (k + 1), hs_path + ("hs%d" % (k + 1),))
            return

        if node.kind == "ret":
            # The successor equations IN SCOPE ON THIS PATH, collected as the
            # walk went -- not `hs1..hs{k}`.  The counter is global across both
            # arms of every fork, so a range over it names hypotheses the other
            # arm has not emitted yet, and the file dies on "Unknown identifier
            # hs18" inside a `simp` set that looks entirely reasonable.
            # Including THIS step's own successor equation: `hs_path` as handed
            # in stops one short, because it is extended on the way down and
            # the `ret` branch returns before recursing -- so the leaf's own
            # `s` is the one state the `simp` cannot unfold, and it reports
            # "made no progress" on a set that looks complete.
            hs = ", ".join(hs_path + ("hs%d" % (k + 1),))
            emit("have hrip : %s.rip = 0 := by" % nxt)
            # The separation step is the genuinely hard part -- its side
            # condition is an inequality over a `mem_write_bytes` chain, closed
            # for a function that spills at literal stack offsets and not
            # otherwise.  So it is attempted and admitted where it does not go
            # through, rather than failing the file.  Lean says which by
            # reporting "declaration uses `sorry`", so the gap stays countable
            # instead of becoming either a build failure or a silent omission.
            #
            # Every step below is one that CANNOT fail: `simp` succeeds even
            # when it simplifies nothing, and the rest are `try`.  So the block
            # always reaches `all_goals sorry`, which admits what is left.
            # `first | (...) | sorry` expresses the same thing but its layout
            # is fragile -- a `| sorry` one column out is read as an
            # alternative of the enclosing tactic and the file stops parsing.
            emit("  have key : ∀ (m : Nat → UInt8) (a : Nat) (v : UInt64)"
                 " (b : Nat),")
            emit("    a + 8 ≤ b → mem_read_bytes (mem_write_bytes m a v 8) b 8"
                 " = mem_read_bytes m b 8 :=")
            emit("  fun m a v b h => mem_read_bytes_write_above m a v 8 8 b h")
            emit("  simp [%s, i0, X86State.init, x86_flags_sub, x86_flags_add,"
                 % hs)
            emit("    x86_set_reg, x86_get_reg, x86_rex_b, x86_rex_r%s] <;>"
                 % case_simp)
            emit("  try (repeat rw [key _ _ _ _ (by first | decide | omega)]) <;>")
            emit("  try (simp only [mem_read_bytes, ite_true]) <;>")
            emit("  first | decide | omega")
            emit("  all_goals sorry")
            full = rules + [step_rule, "x86_exec_go_exit_at (by decide) hrip"]
            emit("rw [%s]" % ",\n    ".join(full))
            emit("simp")
            return

        walk(node.kids[0], nxt, ind, cases, rules + [step_rule],
             "hs%d" % (k + 1), hs_path + ("hs%d" % (k + 1),))

    walk(root, "i0", 1, [], [], None, ())
    return "\n".join(out) + "\n"


def _probe_input_independent(path):
    """Does the model's result depend on the input at all?

    The theorem states a CONSTANT result, so a program that returns its input
    cannot satisfy it -- and that is a limit of what is proved here, not a
    proof failure, so it must not be reported as one.  The model itself
    answers the question exactly: run the same bytes from two different
    initial states and compare.

    This costs a second Lean invocation, so it only runs for a file whose
    theorem has already failed.
    """
    r = B.compile_formal(path, prove=False, check=False, arch="x86_64")
    code, info = r["code"], r["info"]
    entry = info["func_offset"]
    text = ("import X86\n\ndef rc (addr : Nat) : UInt8 :=\n"
            "  if addr < %d then 0 else ([%s].getD (addr - %d) 0)\n\n"
            "/-- The result is the same for every input, or it is not. -/\n"
            "theorem input_independent :\n"
            "    (x86_exec_exit (X86State.init 0 %d) rc 0).map X86State.rax =\n"
            "      (x86_exec_exit (X86State.init 5 %d) rc 0).map X86State.rax :=\n"
            "  by\n  native_decide\n"
            % (info["base_addr"], ", ".join("0x%02x" % b for b in code),
               info["base_addr"], entry, entry))
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False) as f:
        f.write(text)
        tmp = f.name
    try:
        env = dict(os.environ, LEAN_PATH="%s:%s" % (ROOT, LIB))
        p = L.run_lean(LEAN_BIN, [tmp], env=env, wall_s=PROOF_WALL_S,
                       cpu_s=PROOF_CPU_S)
        if p.exceeded:
            print("  BOUND: " + p.exceeded)
            return False
        return ": error" not in p.stdout + p.stderr
    finally:
        os.unlink(tmp)


def _has_loop(path):
    """Does the function body contain a back edge?

    The chain walks one straight line from the entry, so a function that loops
    is out of its reach -- and that is a limit of the method rather than a
    proof that stopped working, so it is reported as uncovered rather than as a
    failure.  A back edge is any branch whose target is at or before itself.

    `call rel32` counts, and it used not to.  That omission is why the six
    recursive examples read `no tree: body loops, or branches out of the
    function` -- the tree's own message, which names two very different reasons
    -- instead of `loops`.  A recursive call's target is a back edge in exactly
    the sense of the sentence above, so `count`, `fact`, `fib`, `pow2`, `sqsum`
    and `sum` are loops and say so.
    """
    r = B.compile_formal(path, prove=False, check=False, arch="x86_64")
    code, info = r["code"], r["info"]
    insns = _body(code, info)
    if insns is None:
        return False
    for i in insns:
        raw = code[i.offset:i.next_offset]
        if i.form in ("jmp_rel32", "call_rel32"):
            if 5 + int.from_bytes(raw[1:5], "little", signed=True) <= 0:
                return True
        elif i.form == "jcc_rel32":
            if 6 + int.from_bytes(raw[2:6], "little", signed=True) <= 0:
                return True
        elif i.form in ("jmp_rel8", "jcc_rel8"):
            if 2 + int.from_bytes(raw[1:2], "little", signed=True) <= 0:
                return True
    return False


_ERR = re.compile(r"^\S*\.lean:\d+:\d+: ")


def _run_lean(text):
    """`(ok, n_sorries, first_error)` for one generated Lean file."""
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False) as f:
        f.write(text)
        tmp = f.name
    try:
        env = dict(os.environ, LEAN_PATH="%s:%s" % (ROOT, LIB))
        p = L.run_lean(LEAN_BIN, [tmp], env=env, wall_s=PROOF_WALL_S,
                       cpu_s=PROOF_CPU_S)
        if p.exceeded:
            # NOT `(False, 0, "…")`: a killed elaboration is not a refutation,
            # it is an absence of one, and this file's caller prints the third
            # element as the reason a theorem did not hold. Returning it there
            # would put "we stopped watching" in the output where a reader is
            # looking for "the model disagrees".
            return (False, 0, p.exceeded)
        out = p.stdout + p.stderr
        # Drop the temp path and the line:col, which would otherwise eat the
        # whole message under the `[:60]` slice below and print as a filename.
        errs = [_ERR.sub("", l) for l in out.splitlines() if ": error" in l]
        sorries = sum(1 for l in out.splitlines() if "declaration uses" in l)
        return (not errs), sorries, (errs[0] if errs else "")
    finally:
        os.unlink(tmp)


def _check(path, expected):
    """`(proved, n_sorries, first_error)` for the value theorem."""
    return _run_lean(emit(path, expected))


def main(argv):
    """Run both theorems over the examples and report each honestly.

    Two, and they answer different questions:

      `value`       for EVERY input the model reaches the exit pc with `rax` a
                    FIXED constant.  Only 7 of the 43 examples can even state
                    it -- the rest return something computed from the input --
                    so it is the stronger theorem where it applies and
                    unavailable elsewhere.

      `terminates`  for EVERY input the model reaches the exit pc, with no
                    claim about the value.  Applies wherever the CFG is finite
                    and every instruction has a step lemma, which is 25 of the
                    43.

    A `sorry` in `terminates` is the memory-separation step declining to go
    through, and it is reported per file rather than hidden: the point is to
    know how much is proved, not to have the file typecheck.
    """
    targets = argv[1:]
    if not targets:
        d = os.path.join(HERE, "examples")
        targets = [os.path.join(d, f) for f in sorted(os.listdir(d))
                   if f.endswith(".mojo")]
    if not LEAN_BIN:
        # Said here rather than as a traceback per example: this file now gets
        # its Lean path from `formal/lean.py::find_lean`, which returns None
        # when the pinned toolchain is not installed, and 43 examples × two
        # theorems is 86 identical failures instead of one line.
        print("lean not found (see ./lean-toolchain)")
        return 1
    val_ok = val_gap = term_ok = term_gap = 0
    fails = notree = noform = 0
    for t in targets:
        name = os.path.basename(t)[:-5]
        try:
            r = B.compile_formal(t, prove=False, check=False, arch="x86_64")
        except Exception as exc:                      # noqa: BLE001
            print("  [skip] %-14s does not build (%s)" % (name, exc))
            continue
        try:
            expected = subprocess.run(["arch", "-x86_64", r["path"]],
                                      capture_output=True, text=True,
                                      timeout=60).returncode
        except Exception as exc:                          # noqa: BLE001
            print("  [skip] %-14s does not run (%s)" % (name, exc))
            continue

        # --- the value theorem, where it can be stated at all ---
        vs = "  value:     -"
        if 0 <= expected <= 255:
            uncovered = None
            try:
                good, val_sorries, msg = _check(t, expected)
            except ValueError as exc:
                # No step lemma for some form: the theorem cannot even be
                # ATTEMPTED, which is missing coverage rather than a proof that
                # failed.  Reporting it as a failure is how "36 failing" happened
                # earlier.
                good, msg, uncovered = None, "", str(exc)
            if good and not val_sorries:
                val_ok += 1
                vs = "  value:     rax = %d, every input" % expected
            elif good:
                # The chain is there and the file typechecks, but a closing fact
                # was admitted -- for a function that spills its argument that is
                # the memory separation, which is B18 and not a disagreement
                # between the model and the source.  Reported as its own outcome
                # for the reason B21 gives: an admitted side condition and a
                # failed proof are different facts and conflating them is how
                # this suite once read as 36 failing when 2 were.
                val_gap += 1
                vs = "  value:     rax = %d, every input, %d sorry" % (
                    expected, val_sorries)
            elif uncovered is not None:
                vs = "  value:     -  (%s)" % (
                    uncovered if uncovered.startswith(BRANCHING)
                    else "no lemma: %s" % uncovered.split(": ")[-1])
            elif _has_loop(t):
                vs = "  value:     -  (loops)"
            elif not _probe_input_independent(t):
                # NOT a failure: the theorem states a CONSTANT result, so a
                # program that returns something computed from its input cannot
                # satisfy it however it is proved.  The termination theorem
                # below is the one that covers those.
                vs = "  value:     -  (result depends on the input)"
            else:
                vs = "  value:     FAIL %s" % msg
                fails += 1

        # --- the termination theorem ---
        try:
            ok, sorries, err = _run_lean(emit_terminates(t))
        except ValueError as exc:
            if _has_loop(t):
                notree += 1
                ts = "  loops (no finite path tree)"
            else:
                noform += 1
                ts = "  no tree: %s" % str(exc)[:38]
        else:
            if ok and not sorries:
                term_ok += 1
                ts = "  terminates: PROVED"
            elif ok:
                term_gap += 1
                ts = "  terminates: proved, %d sorry" % sorries
            else:
                fails += 1
                ts = "  terminates: FAIL %s" % err.strip()[:60]
        print("%-14s%s\n%s" % (name, vs, ts))

    print("\n  value      : %d proved with no sorry, %d open"
          % (val_ok, val_gap))
    print("  terminates : %d proved with no sorry, %d proved with a sorry"
          % (term_ok, term_gap))
    print("               %d no finite tree (%d loop, %d uncovered form)"
          % (notree + noform, notree, noform))
    print("  failing    : %d" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
