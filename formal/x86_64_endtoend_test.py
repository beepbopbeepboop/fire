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
  32, proved with a sorry 0, no finite tree 13 (10 loops, two whose leaves leave
  the function, and one whose run continues into the caller after a `ret`),
  failing 0**; value 3 proved and 12 open.  It was 10 / 14 / 19 / 0 and value
  3 / 0 when the twenty-odd forms below were wired, and 31 / 2 / 12 on
  2026-10-01.

  The `sorry` count reached 0 by two DIFFERENT routes, and the second is why it
  is worth reading rather than celebrating. `augassign` lost its `sorry` to a
  re-generalised lemma (`mov_r64_rm64_sib` was proved as `mov rax, [rsp]` and so
  proved `mov r11, [rsp]` too — the two REX bytes and two destination registers,
  applied by FORM NAME, with the false byte hypotheses admitted by the
  side-condition guard; B2 over a whole addressing mode). `wide_recv` lost its
  `sorry` by ceasing to be PROVED at all: its path contains a `call`, the tree
  made the callee's `ret` the end of the run, and the closing `hrip` claimed
  `rip = 0` where the machine pops the address the `call` pushed. A `sorry` is
  not a uniform unit of missingness — one of them was covering for a claim that
  was wrong — so `no tree: the run continues into the caller` is a BETTER outcome
  than `proved, 1 sorry` and the same number of sorries is not the same strength
  of theorem.

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

    * A path that RETURNS INTO A CALLER is declined, and it is the one limit
      here that is not a gap in the proof but a falsehood in it.  `call` pushes
      a return address and `ret` pops one, so a function that calls another does
      not finish where the callee finishes; the tree used to make every `ret`
      the end of the run, the chain stopped at the callee's return, and the
      closing `hrip : s_N.rip = 0` claimed the exit sentinel where the machine
      has the address after the `call`.  Reported as `no tree: the run
      continues into the caller after the callee's ret`, and `wide_recv` is the
      only example in the corpus it applies to.  Following the return is the fix
      and it needs the separation at each `ret`; see
      `bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`.

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
    #
    # `sub` is here for the reason the guard is in every prologue
    # (`formal/x86_64_codegen.py::_emit_stack_floor_guard`: `SUB R10, BUDGET`,
    # one per function) and not for a corpus example: the arithmetic it needs
    # was already the `else` arm of `_resolve`'s own branch below, DEAD for this
    # form, which is what `x86_step_cmp_ri8`'s theorem was using it for.  So the
    # row is a name plus the `else` arm and the encoding is `x86_step_add_ri32`'s.
    "alu_ri32:add_reg": ("x86_step_add_ri32", False,
                         ["rip", "b0", "b1", "b2", "rex", "w", "mod", "digit",
                          "rm"]),
    # `sub r64, imm32` on a GENERAL register: the same encoding as `add` with
    # digit 5 instead of 0, hence the same side-condition list, and the only
    # member of this family whose flags come from `x86_flags_sub` AND whose
    # successor writes the register back (`cmp` is the other, and it discards
    # the result).
    "alu_ri32:sub_reg": ("x86_step_sub_ri32", False,
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
    # The RIP-relative mode, which is a LOAD-shaped form with the same concrete
    # `dst` and the same truncation -- and the same condition list as
    # `lea_r64_rm64_disp32` MINUS `rm_ne`, because `rm = 5` is the mode and
    # `5 ≠ 4` is not a hypothesis anybody has to discharge.  Everything else,
    # `rm` included, is the same list: the lemma's own hypothesis order, and
    # `_FORMS`'s header is right that a row whose length disagrees with its
    # lemma's is a proof failure rather than a silent gap.  Measured: dropping
    # `rm` shifted `dst_lt` into the position of the lemma's last hypothesis,
    # the application elaborated with eleven metavariables, and the generated
    # file reported `Type mismatch` with both records printed in full and
    # neither naming the form -- on the FIRST `lea` in every image.
    #
    # A separate row rather than another mode of the one above, for the reason
    # `_shapes`' own comment gives: a name that does not say which mode it is is
    # how an unmapped shape used to be satisfied by whichever lemma shared its
    # name.  Two producers, so one row closes both: the stack-floor guard's
    # `lea r11, [rip+&floor]` in every prologue with an entry, and
    # `_emit_global_init`'s RIP-relative `lea` for every address-valued module
    # global.  Here the r/m field is not a register at all but the instruction
    # pointer, so the displacement counts from the END of the instruction and
    # there is no `rm` argument to supply.
    "lea_r64_rip": ("x86_step_lea_r64_rip", False,
                    ["rip", "b0", "b1", "b2", "disp32", "rex", "w", "mod",
                     "rm", "reg", "dst", "dst_lt"]),
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
    # `66 REX.W 0F 6E /r`, `movq xmm, r64`: the GPR-to-SSE move a floating
    # `printf` needs, and the first instruction in this corpus that crosses from
    # one register FILE into another.  Four hypotheses pin the PREFIXES and the
    # opcode apart from the ModRM (`b0` is the `0x66`, `b1` the REX, `b2` the
    # `0F`, `b3` the `6E`), because they are four separate bytes at four
    # separate positions: `b2` and `b3` in particular are the two-byte escape,
    # and a row that took `b2` for the opcode would be a lemma about `0F 6E`
    # without its prefix -- a different, four-byte instruction.
    "movq_xmm_rm64": ("x86_step_movq_xmm_rm64", False,
                      ["rip", "b0", "b1", "b2", "b3", "b4", "rex", "w",
                       "not66", "mod"]),
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
    # `add_reg`'s row with `-` and `($fs)`: digit 5 rather than digit 0, the same
    # `81` encoding and therefore the same length, and the same immediate
    # expression for the same reason the row above states it.  The flags are
    # `$fs` — `x86_flags_sub` — which is the model's digit-5 arm and the same
    # `else` arm of `_resolve` that the `cmp` row below uses; that row is
    # flags-only, this one also writes the register, and the two differ in
    # exactly that.
    "alu_ri32:sub_reg":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) ((x86_get_reg $s "
        "($rm + x86_rex_b $rex)) - $imm) with rip := $next, zf := ($fs).zf, "
        "sf := ($fs).sf, cf := ($fs).cf, of_ := ($fs).of_ }",
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
    # No `alu_ri32:add` row, and its absence is a measurement rather than an
    # oversight: `_shapes` renames the decoder's `alu_ri32:add`/`alu_ri32:sub`
    # to `..._rsp` or `..._reg` by the ModRM byte (ModRM c4 is `add rsp`,
    # anything else is `add r64`), so since that split landed this key has been
    # unreachable -- the successor for `add rax, imm32` is `mov_rm64_imm32`'s
    # neighbourhood and not this.  A row nobody can reach is a second, stale
    # statement of a model's semantics, which is the thing `_SUCCS`' own header
    # warns about; `test_formal_sweep_truth.py` now asserts the two tables hold
    # exactly the same keys, so the next one cannot be added silently.
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
    # The RIP-relative `lea`: same register write, but the base is the END of
    # this instruction rather than a register's value, and there is no `$rm` in
    # the expression at all — which is the point.  A copy of the row above with
    # `$rm` left in would be a proof about `lea [reg + disp]`, and the error
    # would surface as a `Type mismatch` or a `sorry` naming neither the form
    # nor the byte.
    #
    # `Int.ofNat ($m + 7)` verbatim, because this row is compared against the
    # lemma's own conclusion by `exact Option.some.inj` and nothing rewrites in
    # between: the model's own term is `↑m + 3 + 4 + disp` (`x86_mem_addr` builds
    # its return length as `sibExtra + dispN`), which is the same NUMBER and a
    # different TERM, and a successor stating the model's spelling comes back
    # unproved against a lemma stating the length.  Measured both ways: writing
    # `m + 3 + 4` here and there closes by `rfl` too, but it makes the table a
    # copy of how the model happens to spell a length rather than a copy of what
    # the instruction does, and the two sides then have to be changed together.
    "lea_r64_rip":
        "{ x86_set_reg $s $dst (UInt64.ofNat ((Int.ofNat ($m + 7) + $disp).toNat "
        "% 18446744073709551616)) with rip := $next }",
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
    # The successor QUOTES the model's own expressions (`x86_set_xmm` over the
    # ModRM's `reg` and `rm + x86_rex_b rex`), which is B3's rule for a
    # successor table and is not optional here: `x86_set_xmm` is a `match` on
    # the XMM index, so a successor naming an index of its own with a
    # `k = …` hypothesis beside it leaves the goal as two records differing in
    # a `match` (B10).  Nothing is substituted into this row, so `$modrm` is
    # not a placeholder and `$next` is the literal the five bytes imply.
    "movq_xmm_rm64":
        "{ x86_set_xmm $s ((($modrm).toNat >>> 3) &&& 7) "
        "(x86_get_reg $s ((($modrm).toNat &&& 7) + x86_rex_b $rex)) "
        "with rip := $next }",
    "leave":
        "{ $s with rbp := mem_read_bytes $s.mem $s.rbp.toNat 8, "
        "rsp := $s.rbp + 8, rip := $next }",
    # `$rip` and not the model's read inline, because the PATH-TREE emitter has
    # to override it: a `ret` that returns into a caller needs the popped value
    # to be the literal the `call` pushed, and it supplies that as its own named
    # fact (`hpop{k}`) and rewrites the step with it. The default is still the
    # model's own expression -- `emit`, the straight-line emitter, never takes
    # the override and so still quotes the model -- and B12's rule is the reason
    # the override is a LITERAL rather than arithmetic on `$m`.
    "ret":
        "{ $s with rip := $rip, rsp := $s.rsp + 8 }",
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


#: **Every hypothesis about the CODE is computed, not looked up.**  The bytes
#: (`b0`..`b3`), the immediates and the displacements are all closed equalities
#: over `rc`, which is a `def` of an `if` and a list literal and therefore
#: computable at a literal address — so `native_decide` settles each one outright,
#: and the `simp [read_i32_le, read_i8, hb]` that used to stand here is kept only
#: as the fallback.
#:
#: It is not tidiness; it is the difference between a proof and a heartbeat
#: timeout.  `hb` is `all_bytes`, one conjunct per byte of the function, so
#: handing it to `simp` adds one rewrite rule per byte — and each rule makes the
#: simplifier evaluate `rc` at its own literal, so the cost of ONE byte fact
#: grows with the size of the whole function, and there are five byte facts per
#: instruction.  The 45-example corpus is small enough that this never showed:
#: measured on a 24-argument call (164 steps, 220 KB of generated Lean, 579
#: byte-fact side conditions) the old form exhausted `maxHeartbeats 4000000` at
#: `whnf` on step 19's `h_b1` and on step 105's `h_disp`, and the FILE DIED both
#: times — a heartbeat timeout is not a tactic failure, so the `try` guard that
#: admits everything else cannot catch it and admit its way out.  With this, the
#: same file elaborates and reports its remaining gaps as sorries, which is the
#: only shape in which a gap is a number.
#:
#: The fallback is what keeps this strictly a performance change: a fact
#: `native_decide` cannot settle (a non-literal address, or a hypothesis about an
#: address outside the image) still goes through the simplifier and is still
#: admitted by the guard if neither goes through.
_BYTES = "first | native_decide | simp [read_i32_le, read_i8, hb]"


def _resolve(form, raw, addr, prev, k, cases=(), hs_in=None,
             length=1, rip=None, code_name="rc"):
    """`(call, succ)` for one instruction: the step lemma applied at `addr`, and
    the successor expression its conclusion has.

    Both the straight-line and the path-tree emitters go through here, so a form
    cannot be wired up in one and forgotten in the other.

    `rip` overrides a successor's program counter with a LITERAL, which is only
    ever right where the tree knows the address the machine goes to next and the
    model says it reads it out of memory — a `ret` that returns into a caller.
    The caller then proves the value separately and rewrites the step with it, so
    the step is still the model's; see `emit_terminates`.

    `code_name` is the NAME of the code function in the generated file, because a
    successor may quote the model's own reader (`UInt64.ofInt (read_i32_le rc
    (m + 3))` for the digit-immediate forms, the shift count's clamp likewise)
    and the name it quotes has to be the one the file defines.  It was the
    literal `rc` — which is what every emitter in this file defines — and that is
    exactly what made `formal/x86_64_model_coverage_test.py`'s SUCCESSOR check
    unable to see any form that reads an immediate: its generated file defines
    one `scode_i` PER FORM and binds it as `code`, so the successor's `rc` was an
    unbound auto-implicit variable and the claim compared the model stepped at
    one encoding against a successor reading a DIFFERENT one.  `sub r10, 0x780000`
    is what exposed it, and the failure it reported — "the emitter's successor
    disagrees with the model's step" — was the right report about a claim that
    was not the one anybody meant to make.
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
        elif c in ("b0", "b1", "b2", "b3", "b4", "imm", "disp", "disp32",
                   "off"):
            sc.append(sc_(_BYTES))
        elif c in ("dst", "dst_lt", "rm_ne", "rm_ne4", "rm_ne5"):
            # Closed arithmetic on the encoding: the destination register is
            # read out of the ModRM/REX bytes and the addressing-mode exclusions
            # are tests on that same rm, so every one is a literal here.
            sc.append(sc_("decide"))
        elif c in ("rex", "rex2", "w", "mod", "reg", "rm", "rb", "rr", "cc",
                   "lo", "hi", "nsetcc_lo", "njcc", "nzx", "op2", "notrex",
                   "not66", "digit"):
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
    elif form in ("alu_ri32:add_reg", "alu_ri32:sub_reg", "alu_ri32:and",
                  "alu_ri8:cmp"):
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
            imm = "(UInt64.ofInt (read_i8 (%s %d)))" % (code_name, addr + 3)
        else:
            imm = "(UInt64.ofInt (read_i32_le %s %d))" % (code_name, addr + 3)
        a = "(x86_get_reg $s (%d + x86_rex_b $rex))" % rm
        if form == "alu_ri32:add_reg":
            res = "(%s + %s)" % (a, imm)
            extra_succ["$fa"] = "x86_flags_add $s %s %s %s" % (a, imm, res)
        elif form == "alu_ri32:sub_reg":
            # `add_reg`'s row with the operator and the flag function turned
            # over, which is the whole difference between the two: digit 5 is
            # `sub`, so the result subtracts and the flags come from
            # `x86_flags_sub` — the same `$fs` the `cmp` row below uses, and the
            # same subtraction.  Reached only now because the name was missing
            # from the tuple above, which is the whole of this form's wiring:
            # the arithmetic, the flags and the immediate reader were already
            # here and already correct.
            res = "(%s - %s)" % (a, imm)
            extra_succ["$fs"] = "x86_flags_sub $s %s %s %s" % (a, imm, res)
        elif form == "alu_ri32:and":
            res = "(%s &&& %s)" % (a, imm)
            extra_succ["$fl"] = "x86_flags_logic $s %s" % res
        else:
            # `alu_ri32:sub_reg` (digit 5, the stack-floor guard's `SUB R10,
            # BUDGET`) and `alu_ri8:cmp` (digit 7, which computes the same
            # subtraction and throws it away) are the model's ONE digit-immediate
            # subtraction, so they share the arm; they differ in `_SUCCS`, which
            # is where the difference between writing the result back and not
            # writing it back lives.
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
        sh = ("UInt64.ofNat (if (%s %d).toNat ≥ 64 then 64 else (%s %d).toNat)"
              % (code_name, addr + 3, code_name, addr + 3))
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
    elif form == "movq_xmm_rm64":
        # `66 REX 0F 6E /r`: FIVE bytes, and every one of them is at a different
        # offset than for a one-byte opcode.  `raw[2]` is the `0F` escape and the
        # ModRM is `raw[4]` -- the same "an `0F` escape puts the ModRM one byte
        # further out" trap `imul` and `movsx_r64_r8` above record, and one byte
        # further again here because the operand-size prefix pushes everything
        # along.  `$modrm` and `$rex` MUST be set here rather than left to the
        # generic `setdefault` below, which reads the ModRM out of `raw[2]` --
        # that is `0x0f`, so it would supply `0x0f &&& 7 = 7` as the source GPR.
        rex, modrm = raw[1], raw[4]
        extra_args = " %d %d" % (rex, modrm)
        # `$modrm` as a TYPED literal. The successor reads `(($modrm).toNat >>> 3)`
        # because the model reads the ModRM through `UInt8.toNat`, and a bare
        # `220` in Lean source is a `Nat` -- `220.toNat` is "Invalid field toNat",
        # which is a different error naming neither the form nor the byte.
        extra_succ = {"$rex": str(rex), "$modrm": "(%d : UInt8)" % modrm}
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
    elif form == "lea_r64_rip":
        # `REX.W 8D /r` with ModRM mod=00 rm=101: the address is measured from the
        # END of the instruction, so there is no base register to read out of the
        # ModRM and the displacement is four bytes at `m + 3` even though `mod = 0`.
        # That is the whole reason this is its own branch rather than the shared
        # memory one below, which reads `mode = 0` as "no displacement" and would
        # hand the lemma `rm = 5` as the base -- a claim about `lea r, [r11]`.
        #
        # `dst` is the concrete destination for the reason `lea_r64_rm64_disp32`
        # carries one: `x86_set_reg` is a `match` on its index, and the successor
        # names `$dst` on both sides so the step is `rfl` rather than a `match`.
        rex, modrm = raw[0], raw[2]
        reg = (modrm >> 3) & 7
        dst = reg + (8 if rex & 4 else 0)
        disp = int.from_bytes(raw[3:7], "little", signed=True)
        extra_args = " %d %d %d %d (%d)" % (rex, modrm, reg, dst, disp)
        extra_succ = {"$rex": str(rex), "$reg": str(reg), "$dst": str(dst),
                      "$disp": str(disp)}
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
    elif form == "lea_r64_rip":
        # `lea r64, [rip + disp32]`: mod=00 with rm=101, so the r/m field is the
        # instruction POINTER and the displacement is read as a FOUR-BYTE value
        # even though the mode says "no displacement" — which is why this cannot
        # go through the `_MEMORY_DISP_FORMS` branch below, whose `mode == 0` arm
        # supplies no displacement at all (correct for `[rbx]`, wrong here).
        #
        # The `rm` argument is absent from the LEMMA, and it has to be absent
        # here too: the model's `ripRel` arm reads no register, so passing one
        # would be an arity error naming neither the form nor the instruction.
        # `disp` is signed and parenthesised, for the reason the memory branch
        # gives — an unparenthesised negative literal swallows the hypothesis
        # that follows it, and this form's displacement is negative in practice
        # (`lea r11, [rip+&floor]` reaches forward, `rip-relative` loads of a
        # string literal reach back).
        rex, modrm = raw[0], raw[2]
        reg = (modrm >> 3) & 7
        dst = reg + (8 if rex & 4 else 0)
        disp = int.from_bytes(raw[3:7], "little", signed=True)
        extra_args = " %d %d %d %d (%d)" % (rex, modrm, reg, dst, disp)
        extra_succ = {"$rex": str(rex), "$reg": str(reg), "$dst": str(dst),
                      "$disp": str(disp)}
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
    call = "%s %s %s %d%s" % (lemma, prev, code_name, addr, extra_args)
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
    # `x86_ret_post`'s own expression for where a `ret` goes. The DEFAULT, so
    # the straight-line emitter still quotes the model; the path-tree emitter
    # passes `rip=` when it knows the address as a literal, and then it has
    # proved the value itself (see the `hpop` in `emit_terminates`).
    subs["$rip"] = ("(mem_read_bytes $s.mem ($s.rsp.toNat) 8).toNat" if rip is None
                    else str(rip))
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
#:
#: `lea_r64_rip` is the mode with no base register, so its branch above reads the
#: displacement itself -- which is why it is here for the `dst` and NOT in
#: `_MEMORY_DISP_FORMS` below for the displacement: that tuple's branch reads
#: `mod = 0` as "no displacement", and this mode carries four bytes of it.
_LOAD_MEMORY_FORMS = ("mov_r64_rm64_disp8", "mov_r64_rm64_disp32",
                      "mov_r64_rm64_nodisp", "lea_r64_rm64_disp32",
                      "lea_r64_rip")

#: The memory-operand shapes `_resolve` supplies arguments for IN ITS SHARED
#: BRANCH.  The two SIB ones are absent deliberately: they have their own
#: `_resolve` branches above, because a SIB byte puts the displacement one byte
#: further out and its base is read from the SIB rather than from the ModRM's rm
#: field.
#:
#: So is `lea_r64_rip`, and the reason is the same kind of thing: it is in
#: `_LOAD_MEMORY_FORMS` (its lemma takes the concrete `dst`) but its four bytes
#: of displacement sit under `mod = 0`, which the shared branch reads as "no
#: displacement" -- the trap `_shapes`'s `_rip` suffix names a mode for.  The
#: exclusion is a named tuple and the tuple is DERIVED, so a new load shape still
#: cannot be added to one of the two and forgotten in the other.
_OWN_DISPLACEMENT_BRANCH = ("lea_r64_rip",)
_MEMORY_DISP_FORMS = tuple(f for f in _LOAD_MEMORY_FORMS
                           if f not in _OWN_DISPLACEMENT_BRANCH) + (
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


# ── THE ABSTRACT MACHINE ──────────────────────────────────────────────────────
#
# What the path tree decides a branch BY, and why it has to decide one.
#
# A path tree walks every branch outcome, and `_emit_stack_floor_guard` puts two
# conditional branches in EVERY prologue of EVERY program image, so a guarded
# function doubled the number of paths through it: the corpus went from one path
# per program to 94 on `wide_recv`, which is past what a proof can be spent on
# and was refused by `_MAX_CHAIN_STEPS`. Both of the guard's conditions are
# settled by arithmetic over the initial state, so walking both arms is work for
# an answer already known:
#
#   JNE done   has the floor word been parked already?  In the ENTRY function the
#              word reads 0 -- `X86State.init`'s memory is a constant zero
#              function, which is `x86_init_mem_reads_zero` -- so the branch is
#              NOT taken.  In a CALLEE it is what the entry's guard parked, which
#              is non-zero for every input because `X86State.init`'s stack
#              pointer is the LITERAL 0xfffffffffffffff0 and not a function of
#              the input, so the whole comparison is over Python integers.
#
#   JAE ok     is SP still above the floor?  SP on a path is a sum of literal
#              frame movements, so this is `sp_now >= sp_floor` on two literals.
#
# So: this section computes the machine's state as the tree walks, and `_tree`
# asks it at every `jcc`. Nothing here is a proof. Every decision it produces is
# emitted by `emit_terminates` as a `have hdec{k} : x86_cond … = …` whose proof
# has NO `sorry` in it, which is the property that makes the analysis safe to
# have at all: **a decision that is wrong makes Lean REJECT the file rather than
# admit a false claim.** A gap in the table below costs the two arms being walked
# again — which is the state this work started from — and never soundness.
#
# What it must therefore never do is guess. An instruction whose effect is not in
# the table wipes the whole state; a store whose ADDRESS is not a literal drops
# the memory model, because a store anywhere can land on the word a later read
# looks at.

_U64 = 1 << 64

#: `X86State.init`'s stack pointer (`lib/ProofLib.lean`), as a literal. It is
#: read here rather than recomputed: the whole reason a callee's guard is
#: decidable is that this is a constant rather than a function of the input.
_INIT_RSP = 0xFFFFFFFFFFFFFFF0

#: Register indices, from `lib/X86.lean::x86_get_reg`'s own `match`. Named
#: because the number 4 for the stack pointer is otherwise a bare literal in
#: four places, and `x86_get_reg 4` is the model's spelling of `s.rsp`.
_R_AX, _R_CX, _R_DX, _R_BX = 0, 1, 2, 3
_R_SP, _R_BP, _R_SI, _R_DI = 4, 5, 6, 7


def _u64(v):
    """`v` as the 64-bit unsigned integer the model's `UInt64` holds."""
    return v % _U64


def _msb(v):
    """`x86_msb`: sign bit of a 64-bit unsigned value."""
    return v >= 0x8000000000000000


class _Abs:
    """What this emitter knows about the machine at ONE point on ONE path.

    Every slot is a Python `int` holding an exact 64-bit unsigned value, or
    `None` for "not known". It is a CONSTANT PROPAGATION over the instruction
    forms in `_abs_step`, not an interpreter of the program: the tree needs
    three questions answered (`is the flag set?`, `what is in that register?`,
    `what does that address hold?`) and this is the least machinery that answers
    them without guessing.

    `bases` and `loads` are not values but a record of what the walk DID, and
    `_tracked` reads them to decide which facts a decided branch's proof needs:
    a register that was the base of a store and a register that was loaded FROM
    an address are exactly the two ways a later proof comes to depend on this
    step.
    """

    __slots__ = ("regs", "flags", "writes", "mem_ok", "bases", "loads",
                 "broken", "flag_regs", "store_regs")

    def __init__(self):
        # `X86State.init`: every register 0, RSP the literal above, and the
        # FLAGS all clear. RDI is the program's input and stays unknown for the
        # whole walk, which is correct -- it is `n`, the one thing the theorem
        # is quantified over.
        self.regs = [0] * 16
        self.regs[_R_DI] = None
        self.regs[_R_SP] = _INIT_RSP
        self.flags = {"zf": False, "cf": False, "sf": False, "of_": False}
        #: Every 8-byte store on this path, oldest first, as `(address, value)`
        #: with `value` possibly `None`. Not a map, because a later store at the
        #: same address must SHADOW an earlier one and a map that kept the first
        #: would answer with a value the machine overwrote.
        self.writes = []
        self.mem_ok = True
        #: Register indices this walk has used as a memory-operand BASE.
        self.bases = set()
        #: `(register, address)` for every LOAD, so a later proof that needs the
        #: register's value can name the cell it came from.
        self.loads = []
        #: Addresses whose value this walk has been unable to answer for, and
        #: will not try again. See `load`: it is what makes a cell usable as a
        #: CHAIN rather than only at one step.
        self.broken = set()
        #: `(register, address)` for every STORE, the mirror of `loads`: a cell
        #: fact states what the cell HOLDS, and that is this register's value at
        #: that step.
        self.store_regs = []
        #: Registers the LAST flag-setting instruction read. A `jcc` consults
        #: `zf`/`cf`, so this is how `_tracked` learns which registers a decided
        #: branch's proof is going to ask the value facts for — and, through
        #: `loads`, which memory cell each of them was read from.
        self.flag_regs = set()

    def copy(self):
        other = _Abs.__new__(_Abs)
        other.regs = list(self.regs)
        other.flags = dict(self.flags)
        other.writes = list(self.writes)
        other.mem_ok = self.mem_ok
        other.bases = set(self.bases)
        other.loads = list(self.loads)
        other.broken = set(self.broken)
        other.flag_regs = set(self.flag_regs)
        other.store_regs = list(self.store_regs)
        return other

    # ── registers ──
    def get(self, i):
        """`x86_get_reg`, including its `_ => 0` arm for an index past 15."""
        return self.regs[i] if 0 <= i < 16 else 0

    def put(self, i, v):
        if 0 <= i < 16:
            self.regs[i] = None if v is None else _u64(v)

    # ── flags ──
    def flag(self, name):
        return self.flags[name]

    def set_flags(self, zf, sf, cf, of_):
        self.flags = {"zf": zf, "sf": sf, "cf": cf, "of_": of_}

    # ── memory ──
    def store(self, addr, val, base=None, src=None):
        """One 8-byte write, as `mem_write_bytes … addr val 8`.

        `base` is the register the ADDRESS came from and `src` the one the VALUE
        did; neither is a value, and both are recorded because `_tracked` needs
        to know which registers and which cells a later proof will ask about.
        """
        if base is not None:
            self.bases.add(base)
        if src is not None:
            self.store_regs.append((src, addr))
        if addr is None:
            # An unknown address can be the address of anything, including a
            # word a later read asks about, so the memory model is dropped
            # rather than the single write being skipped.
            self.writes = []
            self.mem_ok = False
            return
        self.writes.append((_u64(addr), None if val is None else _u64(val)))

    def load(self, addr, reg=None):
        """The 8 bytes at `addr`, or None if that is not known.

        **A cell this walk could not answer for once, it never answers for again**
        — that is `broken`, and it is what makes a cell usable as a CHAIN rather
        than only at one step. A cell written with an unknown value and then
        written again with a known one would otherwise be answerable at step `k`
        and not at `k - 1`, and the per-step facts `emit_terminates` emits would
        then have a hole in the middle of a chain nothing can fill: the fact at
        `k` reduces one step and hands the rest to the fact at `k - 1`.

        The rule is per ADDRESS and not the coarser "some unknown store sits at
        or below this address", because the coarse rule loses a whole memory
        model for nothing: `wide_recv`'s callee stores through `rbx`, which is a
        pointer the walk cannot follow, and one such store invalidates every
        register read from a STACK slot above it — the struct's own frame — which
        is most of them, and with them every later decision. Measured: with the
        coarse rule `wide_recv` reached 7 leaves; with this one, 1.

        An unknown ADDRESS still costs every cell, because a store anywhere can
        land on any word: that is `mem_ok`, and it is why the guard's trap arm
        becomes undecidable once a frame is addressed through a pointer rather
        than through `rsp`/`rbp`.
        """
        if addr is None or not self.mem_ok:
            return None
        addr = _u64(addr)
        if addr in self.broken:
            return None
        val = 0                         # `X86State.init`'s memory: all zero
        for a, v in reversed(self.writes):
            if a == addr:
                val = v
                break
            if a < addr + 8 and addr < a + 8:
                # Partial overlap: the value would be a mixture of two writes
                # and this model cannot say which bytes. Cannot happen while
                # every store is eight bytes wide, and is here for the day one
                # is not.
                val = None
                break
        if val is None:
            self.broken.add(addr)
            return None
        if reg is not None:
            self.loads.append((reg, addr))
        return val

    def wipe(self):
        """Everything a form outside `_abs_step`'s table may have changed."""
        self.regs = [None] * 16
        self.flags = {"zf": None, "cf": None, "sf": None, "of_": None}
        self.writes = []
        self.mem_ok = False
        self.bases = set()
        self.loads = []
        self.store_regs = []
        self.flag_regs = set()


def _abs_step(prev, form, raw, addr, length):
    """The abstract state AFTER `form` at `addr`.

    `prev` is left alone: every node of the tree gets its own state, because a
    fork's two arms start from the same state and diverge from there, and the
    tree keeps both. `None` in, `None` out — there is no state to copy from an
    unknown one, and a caller that has none must not be handed a guess.

    **Nothing here raises.** A form outside the table, or one whose bytes are
    shorter than the decode below needs, wipes the state instead: this runs
    inside `_tree`, so an exception would take the whole emitter down rather than
    leave one branch undecided, which is the outcome this section is for.
    """
    if prev is None:
        return None
    st = prev.copy()
    # The forms that change nothing this section tracks. `jmp`/`jcc` do not
    # touch a register or a flag, and `movq xmm, r64` writes an XMM register,
    # which nothing here reads.
    if form in ("jcc_rel32", "jcc_rel8", "jmp_rel32", "jmp_rel8",
                "movq_xmm_rm64"):
        return st
    if form == "call_rel32":
        # The return address the model pushes is `UInt64.ofNat (m + 5)` -- the
        # same literal `_tree` reads off the encoding for the address the
        # callee's `ret` will pop, which is what makes the two agree.
        rsp = st.get(_R_SP)
        if rsp is None:
            st.wipe()
            return st
        st.store(_u64(rsp - 8), addr + 5, _R_SP)          # the value is a literal
        st.put(_R_SP, rsp - 8)
        return st
    if form == "ret":
        rsp = st.get(_R_SP)
        st.put(_R_SP, None if rsp is None else rsp + 8)
        return st
    if form == "leave":
        rbp = st.get(_R_BP)
        st.put(_R_BP, st.load(rbp, _R_BP))
        st.put(_R_SP, None if rbp is None else rbp + 8)
        return st
    if form == "push_r64":
        rsp = st.get(_R_SP)
        st.store(None if rsp is None else _u64(rsp - 8), st.get(_R_BP), _R_SP,
                 _R_BP)
        st.put(_R_SP, None if rsp is None else rsp - 8)
        return st
    if form in ("alu_ri32:sub_rsp", "alu_ri32:add_rsp"):
        st.flag_regs = {_R_SP}
        # `48 81 ec id` / `48 81 c4 id`: the immediate is a SIGN-EXTENDED
        # int32 the model turns into a `UInt64`, so it is taken mod 2^64 here
        # too rather than subtracted as a Python negative.
        imm = _u64(int.from_bytes(raw[3:7], "little", signed=True))
        rsp = st.get(_R_SP)
        down = form.endswith("sub_rsp")
        if down:
            res = None if rsp is None else _u64(rsp - imm)
            st.put(_R_SP, res)
            # `x86_flags_sub`, and its `cf` is the unsigned comparison the
            # guard's `JAE` is decided on.
            st.set_flags(None if res is None else res == 0,
                         None if res is None else _msb(res),
                         None if (rsp is None or imm is None) else rsp < imm,
                         None if None in (rsp, imm, res)
                         else (_msb(rsp) != _msb(imm)
                               and _msb(res) != _msb(rsp)))
        else:
            res = None if rsp is None else _u64(rsp + imm)
            st.put(_R_SP, res)
            # `x86_flags_add`, whose `cf` is `res < a`.
            st.set_flags(None if res is None else res == 0,
                         None if res is None else _msb(res),
                         None if (rsp is None or imm is None) else res < rsp,
                         None if None in (rsp, imm, res)
                         else (_msb(rsp) == _msb(imm)
                               and _msb(res) != _msb(rsp)))
        return st
    if form == "cqo":
        # `REX 99`: two bytes and NO ModRM, so it is handled before the ModRM
        # decode below — which reads `raw[2]` and would raise on it. RDX is the
        # sign extension of the whole 64-bit RAX, not of its low word (`cqo`'s
        # own row in `_SUCCS` says which of the two this is).
        a = st.get(_R_AX)
        st.put(_R_DX, None if a is None else (_u64(-1) if _msb(a) else 0))
        return st
    if form == "mov_rm64_imm32":
        st.put(_R_AX, int.from_bytes(raw[3:7], "little", signed=True))
        return st
    if form == "movzx_r64_r8":
        a = st.get(_R_AX)
        st.put(_R_AX, None if a is None else a & 0xFF)
        return st
    if form == "movsx_r64_r8":
        # `REX 0F BE /r`: FOUR bytes with the two-byte escape in the middle, so
        # the ModRM is `raw[3]` and not `raw[2]` — the same off-by-one
        # `_resolve`'s own branch for this form records, and reading `raw[2]`
        # here would take the `0xBE` opcode for a ModRM.
        modrm = raw[3]
        rex = raw[0] if raw[0] & 0xF0 == 0x40 else 0
        dst = ((modrm >> 3) & 7) + (8 if rex & 4 else 0)
        a = st.get((modrm & 7) + (8 if rex & 1 else 0))
        if a is None:
            st.put(dst, None)
        else:
            b = a & 0xFF
            st.put(dst, _u64(b | 0xFFFFFFFFFFFFFF00) if b & 0x80 else b)
        return st

    if len(raw) < 3:
        # A form with no ModRM byte that is not handled above. Wiping rather than
        # raising is the point: `_abs_step` runs inside the TREE walk, so an
        # IndexError here would take the whole emitter down rather than leave
        # one branch undecided.
        st.wipe()
        return st
    # A REX byte is `0x40..0x4F` and nothing else, so the test is the HIGH NIBBLE
    # and not "byte zero": `test rdi, rdi` is `85 FF`, whose first byte is the
    # OPCODE, and reading it as a REX would extend both of its ModRM fields by
    # eight and decide the flag about R15 instead.
    rex = raw[0] if raw[0] & 0xF0 == 0x40 else 0
    modrm = raw[2]
    reg, rm = (modrm >> 3) & 7, modrm & 7
    # `x86_rex_r` and `x86_rex_b`: the model's own decoders, applied to the same
    # REX byte `_resolve` applies them to, so the two cannot disagree about
    # which register a ModRM field names.
    rex_r, rex_b = (8 if rex & 4 else 0), (8 if rex & 1 else 0)
    mod = modrm >> 6
    dst, src = reg + rex_r, rm + rex_b
    # The address of a memory operand. `Int.ofNat v.toNat + disp` then `.toNat`
    # is the model's own spelling, and `Int.toNat` of a negative `Int` is 0 —
    # so a displacement that carries the address below zero is a read of 0
    # here, which is what the model does rather than a guess.
    def _addr(base, disp=0):
        if base is None:
            return None
        v = base + disp
        return _u64(v if v >= 0 else 0)

    def _disp(raw_off, wide):
        if wide:
            return int.from_bytes(raw[raw_off:raw_off + 4], "little", signed=True)
        return raw[raw_off] - 256 if raw[raw_off] > 127 else raw[raw_off]

    if form == "mov_r64_rm64_reg":
        st.put(dst, st.get(src))
        return st
    if form == "mov_rm64_r64_reg":
        st.put(src, st.get(dst))
        return st
    if form == "lea_r64_rip":
        # `lea` computes its address from the END of the instruction, which is
        # what `length` is for: `_resolve` says the displacement counts from
        # `m + 7`, and the seven is this form's length rather than a constant
        # written twice.
        st.put(dst, (addr + length + _disp(3, True)) % _U64)
        return st
    if form == "lea_r64_rm64_disp32":
        st.put(dst, _addr(st.get(src), _disp(3, True)))
        return st
    if form in _MEMORY_DISP_FORMS:
        wide = form.endswith("disp32")
        load = form in _LOAD_MEMORY_FORMS
        base = _R_SP if "sib" in form else src
        a = _addr(st.get(base), 0 if mod == 0 else _disp(3, wide))
        if load:
            st.put(dst, st.load(a, dst))
        else:
            st.store(a, st.get(dst), base, dst)
        return st
    if form in _SIB_STORE_WITH_DISP_FORMS:
        # The SIB byte puts the displacement one byte further out, which is why
        # these two are their own rows in `_resolve` and are here too.
        st.store(_addr(st.get(_R_SP), _disp(4, form.endswith("disp32"))),
                 st.get(dst), _R_SP, dst)
        return st
    if form == "mov_r64_rm64_sib":
        st.put(dst, st.load(st.get(_R_SP), dst))
        return st
    if form == "mov_rm64_r64_sib":
        st.store(st.get(_R_SP), st.get(dst), _R_SP, dst)
        return st
    if form == "alu_rr:test":
        a, b = st.get(src), st.get(dst)
        if a is None or b is None:
            st.set_flags(None, None, False, False)
            return st
        res = a & b
        st.flag_regs = {src, dst}
        # `x86_flags_logic`: ZF and SF from the result, CF and OF CLEARED. The
        # guard's `JNE` is this, and the "cleared" half is why the decision does
        # not need the operands to be equal -- only their AND to be non-zero.
        st.set_flags(res == 0, _msb(res), False, False)
        return st
    if form in ("alu_rr:cmp", "alu_rr:add", "alu_rr:sub"):
        st.flag_regs = {src, dst}
        a, b = st.get(src), st.get(dst)
        if a is None or b is None:
            st.set_flags(None, None, None, None)
            if form != "alu_rr:cmp":
                st.put(src, None)
            return st
        res = _u64(a - b) if form != "alu_rr:add" else _u64(a + b)
        # `x86_flags_sub`: `cf` is the UNSIGNED `a < b`, which is the guard's
        # `JAE` read the other way round, and `of_` is the signed overflow.
        st.set_flags(res == 0, _msb(res), a < b,
                     _msb(a) != _msb(b) and _msb(res) != _msb(a))
        if form != "alu_rr:cmp":
            st.put(src, res)
        return st
    if form in ("alu_rr:and", "alu_rr:or", "alu_rr:xor"):
        st.flag_regs = {src, dst}
        a, b = st.get(src), st.get(dst)
        if a is None or b is None:
            st.put(src, None)
            st.set_flags(None, None, False, False)
            return st
        res = {"alu_rr:and": a & b, "alu_rr:or": a | b,
               "alu_rr:xor": a ^ b}[form]
        st.put(src, res)
        st.set_flags(res == 0, _msb(res), False, False)
        return st
    if form in ("alu_ri32:add_reg", "alu_ri32:sub_reg", "alu_ri32:and"):
        st.flag_regs = {src}
        a = st.get(src)
        imm = _u64(int.from_bytes(raw[3:7], "little", signed=True))
        if a is None:
            st.put(src, None)
            st.set_flags(None, None, None, None)
            return st
        if form.endswith("and"):
            res = a & imm
            st.set_flags(res == 0, _msb(res), False, False)
        elif form.endswith("add_reg"):
            res = _u64(a + imm)
            st.set_flags(res == 0, _msb(res), res < a,
                         _msb(a) == _msb(imm) and _msb(res) != _msb(a))
        else:
            res = _u64(a - imm)
            st.set_flags(res == 0, _msb(res), a < imm,
                         _msb(a) != _msb(imm) and _msb(res) != _msb(a))
        st.put(src, res)
        return st
    if form == "alu_ri8:cmp":
        st.flag_regs = {src}
        a = st.get(src)
        imm = _u64(raw[3] - 256 if raw[3] > 127 else raw[3])
        if a is None:
            st.set_flags(None, None, None, None)
            return st
        res = _u64(a - imm)
        st.set_flags(res == 0, _msb(res), a < imm,
                     _msb(a) != _msb(imm) and _msb(res) != _msb(a))
        return st
    if form.startswith("shift_imm8:"):
        st.flag_regs = {src}
        a = st.get(src)
        # The count is the byte at `m + 3`, which the model clamps at 64. A count
        # this section will not reproduce exactly makes the DESTINATION unknown
        # rather than a wrong number — the count is a byte of the image, not
        # something to round.
        n = raw[3]
        if a is None or n > 31:
            st.put(src, None)
            st.flags = dict(st.flags, zf=None, sf=None)
            return st
        op = form.split(":")[1]
        if op == "shl":
            res = _u64(a << n)
        elif op == "shr":
            res = a >> n
        else:
            # `x86_sign_extend32` first — bit 31 across the top word — and then
            # the logical shift, so the two are one expression here and not two.
            res = (_u64(0xFFFFFFFF00000000) if _msb(a & 0xFFFFFFFF) else a) >> n
        st.put(src, res)
        # The shifts write ZF and SF and LEAVE CF and OF ALONE — the whole
        # difference from every other flag-setting row, and the reason a `jcc`
        # after a shift is decided from the flags the shift did NOT touch.
        st.flags = dict(st.flags, zf=res == 0, sf=_msb(res))
        return st
    if form == "imul_r64_r64":
        a, b = st.get(dst), st.get(src)
        st.put(dst, None if a is None or b is None else _u64(a * b))
        return st                      # and no flags, which is the model's row
    if form == "setcc":
        # `x86_set_reg` writes 1 or 0, zero-extended — the two values the model
        # narrows to (`x86_trunc32_zero`, `x86_trunc32_one`). The destination is
        # the bare `modrm & 7` and carries NO REX.B, which is `_resolve`'s own
        # reading of this row and the one this follows.
        v = _abs_cond(raw[1] - 0x90, st)
        st.put(rm, None if v is None else (1 if v else 0))
        return st
    st.wipe()
    return st


def _abs_cond(cc, abs_):
    """`x86_cond cc` over the abstract state: True, False, or None.

    The condition codes are the model's own (`lib/X86.lean`'s `match`, nibble for
    nibble), transcribed once. `cc` is the OPCODE NIBBLE, not the backend's
    `COND_*` constant, which is the trap `x86_cond`'s own comment warns about:
    the two are different permutations and reading one as the other evaluates
    the wrong condition — which would not be caught here, because the emitted
    `have` is proved against `x86_cond` and would simply fail.
    """
    zf, cf, sf, of_ = (abs_.flag(k) for k in ("zf", "cf", "sf", "of_"))

    def both(a, b):
        return None if a is None or b is None else (a and b)

    def either(a, b):
        return None if a is None or b is None else (a or b)

    def neg(a):
        return None if a is None else (not a)

    if cc == 0:
        return of_
    if cc == 1:
        return neg(of_)
    if cc == 2:
        return cf
    if cc == 3:
        return neg(cf)               # ae / nb / nc
    if cc == 4:
        return zf
    if cc == 5:
        return neg(zf)               # ne / nz
    if cc == 6:
        return either(cf, zf)
    if cc == 7:
        return both(neg(cf), neg(zf))
    if cc == 8:
        return sf
    if cc == 9:
        return neg(sf)
    if cc == 10:
        return zf
    if cc == 11:
        return neg(zf)
    if cc == 12:
        return None if sf is None or of_ is None else sf != of_
    if cc == 13:
        return None if sf is None or of_ is None else sf == of_
    if cc == 14:
        return None if sf is None or of_ is None else (zf or sf != of_)
    return None if sf is None or of_ is None or zf is None else (
        not zf and sf == of_)


#: What a decided branch's proof has to unfold, per form on the path.
#:
#: These are the definitions the form's SUCCESSOR expression (`_SUCCS`) mentions,
#: so the set is derived from the same table the successor is transcribed from
#: and a form that needs one it does not list fails to close — visibly, with no
#: `sorry` to hide it. The point of listing them per form rather than passing one
#: global set is the size of the `simp`: the whole set on every decision is what
#: made the closing `simp` unaffordable, and Lean warns about every argument it
#: does not use, so an over-broad set is both slow and noisy.
_SIMP_FORMS = {
    "push_r64": ("x86_get_reg", "mem_write_bytes"),
    "alu_ri32:sub_rsp": ("x86_get_reg", "x86_flags_sub"),
    "alu_ri32:add_rsp": ("x86_get_reg", "x86_flags_add"),
    "mov_rm64_imm32": (),
    "alu_ri32:add_reg": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "x86_flags_add"),
    "alu_ri32:sub_reg": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "x86_flags_sub"),
    "alu_ri32:and": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "x86_flags_logic"),
    "alu_ri8:cmp": ("x86_get_reg", "x86_flags_sub"),
    "mov_r64_rm64_reg": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "x86_rex_r"),
    "mov_rm64_r64_reg": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "x86_rex_r"),
    "lea_r64_rm64_disp32": ("x86_get_reg", "x86_set_reg", "x86_rex_b"),
    "lea_r64_rip": ("x86_set_reg", "UInt64.ofNat"),
    "mov_r64_rm64_sib": ("x86_get_reg", "x86_set_reg", "mem_read_bytes"),
    "mov_rm64_r64_sib": ("x86_get_reg", "x86_set_reg", "mem_write_bytes"),
    "mov_r64_rm64_disp8": ("x86_get_reg", "x86_set_reg", "mem_read_bytes"),
    "mov_r64_rm64_disp32": ("x86_get_reg", "x86_set_reg", "mem_read_bytes"),
    "mov_r64_rm64_nodisp": ("x86_get_reg", "x86_set_reg", "mem_read_bytes"),
    "mov_rm64_r64_disp8": ("x86_get_reg", "x86_set_reg", "mem_write_bytes"),
    "mov_rm64_r64_disp32": ("x86_get_reg", "x86_set_reg", "mem_write_bytes"),
    "mov_rm64_r64_nodisp": ("x86_get_reg", "x86_set_reg", "mem_write_bytes"),
    "mov_rm64_r64_sib_disp8": ("x86_get_reg", "x86_set_reg", "mem_write_bytes"),
    "mov_rm64_r64_sib_disp32": ("x86_get_reg", "x86_set_reg", "mem_write_bytes"),
    "movzx_r64_r8": ("UInt64.ofNat",),
    "movsx_r64_r8": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "x86_sign_extend8"),
    "alu_rr:add": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "x86_rex_r",
                   "x86_flags_add"),
    "alu_rr:sub": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "x86_rex_r",
                   "x86_flags_sub"),
    "alu_rr:and": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "x86_rex_r",
                   "x86_flags_logic"),
    "alu_rr:or": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "x86_rex_r",
                  "x86_flags_logic"),
    "alu_rr:xor": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "x86_rex_r",
                   "x86_flags_logic"),
    "alu_rr:cmp": ("x86_get_reg", "x86_rex_b", "x86_rex_r", "x86_flags_sub"),
    "alu_rr:test": ("x86_get_reg", "x86_rex_b", "x86_rex_r", "x86_flags_logic"),
    "shift_imm8:shl": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "UInt64.ofNat"),
    "shift_imm8:shr": ("x86_get_reg", "x86_set_reg", "x86_rex_b", "UInt64.ofNat"),
    "shift_imm8:sar": ("x86_get_reg", "x86_set_reg", "x86_rex_b",
                       "x86_trunc32", "x86_sign_extend32"),
    "imul_r64_r64": ("x86_get_reg", "x86_set_reg", "x86_rex_b"),
    "cqo": ("x86_cqo",),
    "setcc": ("x86_get_reg", "x86_set_reg", "x86_trunc32"),
    "call_rel32": ("UInt64.ofNat", "mem_write_bytes"),
    "ret": ("mem_read_bytes",),
    "leave": ("mem_read_bytes",),
}

#: What every decided branch's proof needs whatever the path: the condition
#: itself (the goal is about `x86_cond`) and the flag accessor the
#: flag-setting instructions' successors mention — `x86_flags_*` compute `sf`
#: and `of_` with it, and `simp` folds the whole record whether it wants to or
#: not.
_DECISION_SIMP = ("x86_cond", "x86_msb")


#: `X86State.init`'s register file, as the emitter's `hval0` states it: every
#: register 0 except RSP (the literal stack pointer) and RDI (the program's
#: input, which is the one thing the theorem is quantified over and so is NOT a
#: literal). Built from an `_Abs` rather than written out, so it cannot drift
#: from the walk's own starting state.
_INIT_FACTS = {r: v for r, v in enumerate(_Abs().regs) if v is not None}

#: `X86State`'s register FIELD names, in `x86_get_reg`'s order.
#:
#: The per-step facts below are stated about `s{r}.<field>` rather than about
#: `x86_get_reg s{r} i`, and that is not cosmetic: a fact in the `x86_get_reg`
#: spelling cannot be applied to the arithmetic a successor builds on a register
#: read, because the successor's own `x86_get_reg` is simplified to the field
#: projection BEFORE the hypothesis is matched — measured, `simp [hs1, hval0]`
#: left `(X86State.init n E).rsp - 8 = …` in the goal and `decide` failed on it
#: with "Expected type must not contain free variables". Stated as the
#: projection, it rewrites. The order is `x86_get_reg`'s own `match`, so the two
#: cannot come to disagree about which field is which register.
_REG_FIELDS = ("rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",
               "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15")


def _decision_simp(forms, path):
    """The `simp` argument list for a decision taken on `path` at `forms`.

    `path` is this path's own equations — the branch's `hs{k}` plus the per-step
    `hval` fact that states the fields the decision reads — and `forms` are the
    instructions that produced them. Both halves are needed and neither is
    enough: the equations without the definitions stay a nest of records, and
    the definitions without the equations never fire.

    **`mem_read_bytes` is NOT in the set, and that is measured.** The value of a
    memory cell comes from the `hval` facts, and a `simp` able to unfold the read
    itself will unfold it BEFORE it matches the hypothesis that states it,
    leaving an `ite` chain no later tactic can use. The library lemma
    `x86_init_mem_reads_zero` looks necessary for the same reason — the initial
    state's zeroed memory IS the floor word's value at the entry guard — and is
    not, because `hval0` states that value over `i0` and is proved with
    `[i0, X86State.init, mem_read_bytes]`, which is the one place the read is
    unfolded on purpose.
    """
    names = set(_DECISION_SIMP)
    for form in forms:
        names.update(n for n in _SIMP_FORMS.get(form, ())
                     if n not in ("mem_read_bytes", "mem_write_bytes"))
    return ", ".join(list(path) + sorted(names))


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
    `state`), "jmp" (one, unconditional), "ret" (none: the run is over) or
    "leaves" (none, and NOT stepped: the run is at this instruction and the
    image ends there — see `_tree`'s `call_rel32`).

    `cond` is a `jcc`'s DECIDED condition — True, False, or None for the two
    arms `by_cases` splits between. A decided `jcc` has ONE kid, the one its
    condition selects, and `emit_terminates` emits the decision as a proved fact
    instead of a `by_cases`; see the abstract machine above for why the guard's
    two branches are settled rather than walked.

    `k` is this node's index in the emitted chain — `s{k}` is the state its step
    starts in — and it is stamped by `_index` over the FINISHED tree rather than
    by a counter inside `emit_terminates`' walk, which reads it off the node
    instead of keeping its own. One number, not two: the walk cannot come to
    disagree with the build about which step is which, and `_tracked` — the
    pre-pass that decides how many per-step value facts to emit — has the same
    numbers before the walk runs at all. `abs` is the abstract machine's state as
    this instruction is about to run, and `after` the state it leaves, which is
    what `hval{k+1}` is about.

    `halt` is set by `_leaf_halts` and is the index of this leaf's disjunct in
    `emit_terminates`' statement, or None for a node that is not a leaf. It lives
    on the node rather than in a counter beside the walk so the two traversals
    cannot come to disagree about which leaf is which: the statement is written
    before the walk runs, so it has to know the leaves in advance, and two
    counters incremented in step are two answers to one question.
    """
    __slots__ = ("insn", "form", "raw", "addr", "kind", "state", "succ", "kids",
                 "halt", "cond", "k", "abs", "after", "write")

    def __init__(self, insn, form, raw, addr, kind, state, succ):
        self.insn, self.form, self.raw, self.addr = insn, form, raw, addr
        self.kind, self.state, self.succ = kind, state, succ
        self.kids = []
        self.halt = None
        self.cond = None
        self.k = None
        self.abs = None
        #: The abstract state AFTER this instruction, which is the state the
        #: emitted `hval{k+1}` is about — `abs` is the one BEFORE it, and the
        #: two are one step apart, which is the step the fact closes.
        self.after = None
        #: `(address, value)` if THIS instruction stored, else None. Read off
        #: the abstract machine's own write list rather than off a table of
        #: which forms are stores, so the two cannot disagree about it.
        self.write = None


class _NoTree(ValueError):
    """`_tree` declined to build a path, with the REASON as a kind.

    B21's lesson, one more time: three different outcomes — no step lemma, a
    loop, and a path that leaves the function — were all being reported as
    failures, and at one point the suite read "36 failing out of 43" when the
    real number was 2. A fourth kind joins them, and it is the only one of the
    four that means the theorem could not be TRUE rather than that it was not
    proved: the path reaches a `ret` that returns into a caller, so the chain
    would have to continue past the frame the prover stops at.

    It is a distinct class rather than a message prefix so the reporter cannot
    come to depend on parsing English to tell the cases apart.
    """

    def __init__(self, kind, detail):
        super().__init__(detail)
        self.kind = kind


def _tree(code, info, shapes):
    """The path tree from the entry, or None if it loops or leaves the body.

    A loop is reported as None rather than walked: the chain proves one path, so a
    back edge has no finite unfolding here.  Four of the examples have one and
    they are named in the test output as needing induction.

    **A `call` pushes a return address, and that is what makes `rets`.**  The
    instruction after the call is the address the callee's `ret` will pop, so it
    goes on a LIFO rather than being stepped here; and a `ret` with a non-empty
    `rets` is NOT the end of the run — see the `ret` branch, which is where the
    interesting part is. The stack exists so that case can be RECOGNISED: a tree
    that treated every `ret` as the end could not tell "this program finishes
    here" from "this program returns to its caller", and it emitted a false
    theorem for the second.

    Reading the return address off the encoding (`m + 5`) rather than off
    `node.succ` is deliberate: it is the same literal the model's
    `x86_step_call_rel32` pushes (`UInt64.ofNat (m + 5)`), which is what makes
    the two agree about where the machine goes next.

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

    **A BRANCH WHOSE CONDITION IS SETTLED IS NOT SPLIT.**  `abs_` is the abstract
    machine's state on this path (see the section above), and a `jcc` whose flags
    it knows is followed into the ONE arm its condition selects, with the
    decision recorded on the node for `emit_terminates` to prove. Without it
    every guarded prologue doubled the paths through it, because the stack-floor
    guard puts two conditional branches in every prologue of every image — which
    is what `_MAX_CHAIN_STEPS` had to be measured against.

    **The step index is stamped on the FINISHED tree, by `_index`, in the walk's
    own order**, and `emit_terminates` reads it off the node instead of counting
    for itself. Both halves are load-bearing: `build` walks a node's children
    before handing the node back, so numbering as the tree is built is
    post-order and would make `s3` name different steps in the two; and
    `_tracked` needs the numbers before the walk starts, because it decides how
    many per-step value facts a decided branch's proof will need.
    """
    base, entry = info["base_addr"], info["func_offset"]
    by_addr = {base + i.offset: (i, f, r) for i, f, r in shapes}
    deep = max(256, sys.getrecursionlimit() - 200)

    def done(node, abs_, after=None):
        """Record the incoming state and this step's store, and hand the node back.

        NOT the step index: `build` creates a node and then walks its children,
        so numbering here would be post-order while the emitter's walk is
        pre-order, and the two would disagree about which step is `s3`. The
        index is stamped by `_index` over the finished tree, in the walk's own
        order.
        """
        node.abs = abs_
        node.after = after
        if after is not None and len(after.writes) > len(abs_.writes):
            node.write = after.writes[-1]
        return node

    def build(addr, state, abs_, depth, seen, rets):
        if depth > deep or addr in seen:
            return None
        seen = seen | {addr}
        got = by_addr.get(addr)
        if got is None:
            return None
        insn, form, raw = got
        # What the machine holds AFTER this instruction, which is what a `jcc`
        # reads: the flags `x86_cond` consults are the ones this instruction
        # left behind, not the ones the state it started in carried.
        after = _abs_step(abs_, form, raw, addr, insn.length)
        if form in ("jcc_rel32", "jcc_rel8"):
            off = (int.from_bytes(raw[2:6], "little", signed=True)
                   if form == "jcc_rel32"
                   else int.from_bytes(raw[1:2], "little", signed=True))
            # The displacement is relative to the END of the instruction, not
            # to its first byte, so the length is part of the target address.
            n = 6 if form == "jcc_rel32" else 2
            nxt = addr + n
            node = _Node(insn, form, raw, addr, "jcc", state, nxt)
            cc = raw[1] - 0x80
            dec = _abs_cond(cc, after)
            if dec is None:
                taken = build(addr + n + off, None, after, depth + 1, seen, rets)
                fell = build(nxt, None, after, depth + 1, seen, rets)
                if taken is None or fell is None:
                    return None
                # `by_cases h : P` presents the `P` case FIRST, so the taken path
                # must be kids[0] or each arm gets the other's address.
                node.kids = [taken, fell]
                return done(node, abs_, after)
            # DECIDED.  One arm, and the arm its condition selects — `kids[0]`
            # is the branch target, so `dec` is exactly the index. The other arm
            # is never BUILT, which is the point: the guard's trap arm is a
            # `call exit(2)` out of the image, and building it is what put a
            # halt-address disjunct in every example's theorem and a second
            # copy of the whole chain below it in the file.
            kid = build(addr + n + off if dec else nxt, None, after,
                        depth + 1, seen, rets)
            if kid is None:
                return None
            node.cond = dec
            node.kids = [kid]
            return done(node, abs_, after)
        if form in ("jmp_rel32", "jmp_rel8"):
            off = (int.from_bytes(raw[1:5], "little", signed=True)
                   if form == "jmp_rel32"
                   else int.from_bytes(raw[1:2], "little", signed=True))
            node = _Node(insn, form, raw, addr, "jmp", state, addr + off)
            node.kids = [build(addr + off, None, after, depth + 1, seen, rets)]
            return None if node.kids[0] is None else done(node, abs_, after)
        if form == "call_rel32":
            # **A CALL THAT LEAVES THE IMAGE IS A LEAF**, and which call that is
            # in practice is the guard's: the stack-floor guard's `exit` goes to a
            # `__TEXT,__stubs` trampoline outside every function, and `build`
            # declines anything it cannot decode -- so a tree that FOLLOWED it
            # returned None and the whole function came back as "body loops, or
            # branches out of the function", a message naming two reasons when
            # there is one.  `e11f066d` put the guard in every prologue, so
            # EVERY x86-64 image has one and the refusal was every example in the
            # corpus, for want of two step lemmas and then for want of this.
            #
            # It used to get its OWN node kind, distinguished by address out of
            # `info["compiler_traps"]` (`formal/x86_64_codegen.py`'s
            # `_emit_call_exit`, which also publishes them for
            # `formal/x86_64_proof_gen.py`, a separate consumer that still needs
            # them), and the chain that reached one ended with an ADMITTED
            # closing `htrap{k}` rather than a `ret`'s `hrip`.  That was honest
            # about the machine -- it really does leave the program there, exiting
            # with status 2, and the model has no bytes for the stub -- and it
            # admitted "the run reaches the exit pc", which is NOT true of this
            # path and was therefore a `sorry` per leaf in every image.
            #
            # The `leaves` case below says the thing that IS true instead ("the
            # run reaches the call"), proves it without an admission, and covers
            # every other call out of the image besides the guard's -- so the two
            # were one concern with two implementations and the weaker one is
            # gone.  The naming lesson it was carrying survives in `hhalt{k}`,
            # which is deliberately not `hrip`: `hrip` is this emitter's name for
            # the exit sentinel at a `ret`, and a reader must be able to tell the
            # two holes apart.
            #
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
            # so.
            #
            # The callee is walked with a FRESH `seen`, because the caller's
            # `seen` cannot cross a frame boundary: calling the same function
            # twice in a row is two calls and not a cycle, and sharing `seen`
            # made the second one look like a loop -- `wide_recv` calls one
            # method body three times (`set_x`, `get_x`, `get_y`, all the same
            # address) and came back as "body loops, or branches out of the
            # function", naming two reasons when there is one. A loop INSIDE the
            # callee is still caught, because the callee's own addresses
            # accumulate as it steps.
            #
            # A BACKWARD call is a back edge and is the honest answer here, the
            # same test `_has_loop` makes on the same bytes: `count`, `fact`,
            # `fib`, `pow2`, `sqsum` and `sum` all recurse, so their target is at
            # or below the call and they report `loops` with no tree built at
            # all.  Left to a fresh `seen` they would recurse in PYTHON until the
            # interpreter's limit, which reaches the same answer by a much worse
            # route.
            off = int.from_bytes(raw[1:5], "little", signed=True)
            if off + 5 <= 0:
                return None
            target = addr + 5 + off
            if target not in by_addr:
                # **A CALL THAT LEAVES THE IMAGE IS A LEAF, and the halt address
                # is the CALL's own address** -- the same answer the arm64
                # generator gives, in `_call_boundary`'s "opaque" kind and
                # `_gen_universal_e2e_cfg`'s `exit_at`, and for the same reason.
                #
                # What the model says happens here is the whole question, so it
                # is worth writing down rather than inferring: `rc` is 0 outside
                # the image (`_header`), `x86_step_plain` has no arm for the byte
                # 0x00 and so `x86_step` returns `none`, and
                # `x86_exec_go_exit`'s `none` branch means "the run ended with
                # nothing" (`x86_exec_go_exit_stuck`). So a run that steps onto
                # such an address does not reach the exit sentinel -- the
                # theorem as stated was FALSE for it, and no tree could prove
                # it. What `x86_exec_go_exit` stops on is `st.rip = exit`
                # BEFORE it steps, so naming the CALL's address as the halt
                # address makes the run stop one instruction earlier and the
                # claim becomes the one the model supports: the run REACHES the
                # call. That is the arm64 half's own words -- "the fix is not to
                # admit the `none` branch but to state the theorem the model CAN
                # support, with the call as the halt address" -- and admitting
                # the `none` branch is not available here anyway: `= none` over
                # `Option` also covers running out of fuel, so it says nothing
                # about where the run ended.
                #
                # **Which paths reach one is not a detail.** The stack-floor
                # guard puts one in every prologue of every program image
                # (`_emit_stack_floor_guard`), so this case is the guard's trap
                # arm rather than a rarity: `exit(2)` with the target in the C
                # library. Walking it as an ordinary node is what made every
                # program in the corpus report `body loops, or branches out of
                # the function` -- which names two reasons when the real one is
                # the third, and `bugs/FORMAL_x86_64_the_stack_floor_guards_exit_call_leaves_the_image.md`
                # is that report with the measurement behind it.
                node = _Node(insn, form, raw, addr, "leaves", state, addr)
                node.kids = []
                return done(node, abs_, after)
            node = _Node(insn, form, raw, addr, "jmp", state, target)
            node.kids = [build(target, None, after, depth + 1, frozenset(),
                              rets + (addr + 5,))]
            return None if node.kids[0] is None else done(node, abs_, after)
        if form == "ret":
            # A `ret` is the end of the RUN only when there is nothing to return
            # to: `X86State.init` gives a stack of zeroes, so the OUTERMOST
            # `ret` pops address 0 and `x86_exec_go_exit` stops there.  A `ret`
            # with a frame to return to pops the return address the matching
            # `call` pushed, the machine carries on in the CALLER, and the
            # address it pops is a literal in the image -- not 0.
            #
            # Treating every `ret` as the end is what made this prover emit a
            # theorem that is FALSE rather than one it could not prove: the
            # chain stopped at the callee's return and the closing fact
            # `s_N.rip = 0` claimed the run had reached the exit sentinel, while
            # the model says `s_N.rip` is `(mem_read_bytes …)`, which is the
            # address after the `call`.  Nothing reported it: `simp` grinds on
            # a goal that is not true until a heartbeat or wall bound fires, and
            # that reads as "the chain is too long" rather than "the chain
            # claims something untrue" -- which is the diagnosis the 24-argument
            # program in `bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`
            # was filed with, and it is not what is wrong.
            #
            # So the return is FOLLOWED, which is the fix, and it is not free.
            # The step after a `ret` has to know `s_k.rip`, and the model says
            # that is `(mem_read_bytes s_{k-1}.mem s_{k-1}.rsp.toNat 8).toNat`:
            # a value read out of the frame, so the emitter states it as its own
            # named fact `hret{k}` and rewrites the successor's `rip` with it
            # (`rw [hret{k}]`), after which the rest of the chain is ordinary
            # again.  See `emit_terminates` for how `hret{k}` is proved and what
            # it costs where it does not go through, and for the bug doc's
            # remaining boundary.
            #
            # The address is the top of `rets`, which the `call` pushed as
            # `UInt64.ofNat (m + 5)` -- read off the ENCODING at the `call`, so
            # the two agree about where the machine goes next.
            #
            # `seen` is passed on UNCHANGED rather than reset: the callee's own
            # addresses have been accumulating since the `call` branched off, so
            # a continuation that walks back into one is a genuine revisit. The
            # `call` resets it in the other direction -- the callee starts fresh
            # -- because a second call to the same body is two calls, not a
            # cycle, and the caller's `seen` cannot cross a frame boundary.
            if rets:
                node = _Node(insn, form, raw, addr, "ret", state, rets[-1])
                kid = build(rets[-1], None, after, depth + 1, seen, rets[:-1])
                if kid is None:
                    # Its own reason, and not `None`: a continuation that does
                    # not walk is a different thing from a body that loops, and
                    # B21 is the whole argument for saying which. It is also
                    # unreachable for the corpus — a return address is `m + 5`
                    # for a `call` in the same function, so it is inside the body
                    # by construction — which is what makes this a bound rather
                    # than a gap.
                    raise _NoTree(
                        "call",
                        "the callee's ret returns into the caller and the "
                        "continuation does not walk")
                node.kids = [kid]
                return done(node, abs_, after)
            return done(_Node(insn, form, raw, addr, "ret", state, None),
                        abs_, after)
        node = _Node(insn, form, raw, addr, "seq", state, addr + insn.length)
        node.kids = [build(addr + insn.length, None, after, depth + 1, seen, rets)]
        return None if node.kids[0] is None else done(node, abs_, after)

    try:
        root = build(entry, "i0", _Abs(), 0, frozenset(), ())
    except RecursionError:
        # One Python frame per instruction, so a straight line longer than the
        # interpreter's own limit cannot be walked at all.  `None` is the answer
        # a loop gets, which is what a path this long looked like before the loop
        # test became a revisited address -- and it is a graceful "no tree"
        # rather than an exception that takes the whole suite with it.
        return None
    if root is None:
        return None
    _index(root)
    return root


#: How much of a "no tree" message the screen shows, by KIND -- and `None`
#: means "all of it".  The `form` branch is the one that matters: its message is
#: `no step lemma wired for: <the forms>`, so 38 characters of it are 38 minus
#: 24 of boilerplate, and a function with two unmodelled forms lost the second
#: one to the ellipsis.  A reader who cannot see WHICH form has no lemma cannot
#: act on the row at all, and the form is the whole content of the message --
#: there is nothing else in it to protect.  The `call` branch keeps its bound
#: because its message is English prose rather than a list.
_NO_TREE_CHARS = {"form": None, "call": 60, "loops": 0, "size": 0}


#: The most step equations one generated file may contain, and the refusal that
#: says so by name.
#:
#: **It is the sum over every PATH, not the tree's size**, because that is what
#: the file's cost is: each leaf emits its own closing `simp` over its own path,
#: so a tree of N nodes and L leaves emits about `N * L` step equations. It is
#: measured, not guessed, and in the unit that predicts the time:
#:
#:   fixture                        steps   leaves   emitted   Lean
#:   TestX86EndToEndEmitter.STRAIGHT  ~230      4      825 lines   11 s
#:   TestX86EndToEndEmitter.SOURCE     ~480     10     1624 lines   24 s
#:   formal/examples/bittest          457     10     2338 lines      --
#:   formal/examples/wide_recv      12241     94   29908 lines      --
#:
#: so ~15 s per 1000 lines on the two that are measured, and 2000 steps is
#: roughly 10 000 lines and two and a half minutes -- inside `PROOF_WALL_S`
#: (1500 s) with room.
#:
#: **What the bound is for, now that the guard is decided.** It was `wide_recv`:
#: the stack-floor guard put two conditional branches in every prologue, a path
#: tree walked every branch outcome, and five guarded functions took it from one
#: path to 94 leaves and 12 241 step equations -- past the bound, and past what a
#: proof can be spent on, since attempting it costs 1500 s of wall and then
#: reports a FAILURE whose message is about the clock (B21's lesson arriving
#: from the other side: an unaffordable attempt reported as a FAILURE is worse
#: than an admitted gap, because the failure is 25 minutes that say nothing and
#: the gap is one number). So the tree is refused, BY NAME and with its size in
#: the line, which is what the gap is.
#:
#: The guard's own branches are now DECIDED (the abstract machine above), which
#: is what that refusal's own docstring said was the fix and is not a bigger
#: bound: `wide_recv` is one path of 150 steps again and elaborates in 162 s.
#: The bound stays, because the doubling it was measured against is still what
#: any branch the machine cannot settle does — `twoifs` and `elif3` are four
#: leaves each and `deepif` three, every one of them a branch on the program's
#: INPUT, and a program with four input-dependent branches is 16 paths whatever
#: else is true of it.
#:
#: The table above is the BEFORE state and is kept as it is, because the ratio
#: is the claim: the same fixtures are now 1, 1, 4 and 1 leaves — `ret42`,
#: `SOURCE`, `bittest`, `wide_recv` — by `emit_terminates` alone, which is
#: Lean-free and takes a second over the whole corpus.
_MAX_CHAIN_STEPS = 2000


def _no_tree_line(kind, detail):
    """The one line the screen shows for a path that is not a theorem."""
    if kind == "loops":
        return "  loops (no finite path tree)"
    if kind == "size":
        # Its own shape rather than a prefix, for the same reason `loops` has
        # one: the number IS the content, so nothing may truncate it.
        return "  too large to prove: %s" % detail
    n = _NO_TREE_CHARS.get(kind)
    return "  no tree: %s" % (detail if n is None else detail[:n])


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


def _index(root):
    """Stamp every node with its step index, in the walk's order.

    The order IS the one `emit_terminates`' walk uses — this node, then `kids[0]`,
    then `kids[1]`, which is `_paths`' order too — and that has to be said rather
    than assumed: `_tree` builds a node's children BEFORE handing the node back,
    so numbering as the tree is built would be post-order, and `s3` would name a
    different step in the two. It is a third traversal of the same shape as
    `_leaf_halts`' and for the same reason: the statement is written before the
    walk runs, so the numbers have to exist before it does.

    It runs on the FINISHED tree, which is what makes it agree with the walk:
    a node the build discarded is not here to be numbered.
    """
    counter = [0]

    def visit(node):
        node.k = counter[0]
        counter[0] += 1
        for kid in node.kids:
            visit(kid)

    visit(root)
    return counter[0]


def _tracked(root):
    """`(regs, cells, upto)` for the per-step value facts a proof will need.

    `regs` is every register a decided branch's proof can come to read, and
    `cells` every address it can come to read memory from; `upto` is the last
    step index any decided branch sits at, so `emit_terminates` emits value
    facts for steps `1 … upto` and none after — the facts exist to feed a
    decision, and a path with no decision past a point pays for none.

    **Where the sets come from is the whole of it, and it is the abstract
    machine's own record rather than a guess.** A register enters `regs` because
    something used it as a memory base or loaded a cell into it, and a cell
    enters `cells` because a tracked register was loaded from it. Anything a
    decided condition reads therefore has a fact by construction, which is the
    property that keeps a MISSING conjunct from turning into a failed file:
    `hval`'s proof reduces one step and hands the rest to the previous fact, so a
    field nothing states is left in the goal unsolved.

    `rsp` and `rbp` are in `regs` whatever else is, because they are what the
    prologue moves and what every frame store is addressed through.

    It is a PRE-PASS over the finished tree, and it has to be: the facts are
    emitted per step, while the walk goes, so the walk needs to know the whole
    set before it emits the first one. The walk order is the tree order — the
    same recursion, `kids[0]` then `kids[1]` — so a fact emitted on one arm is
    never one another arm needed, and the step indices it reads (`node.k`, stamped
    by `_tree`) are the same ones the walk uses.
    """
    regs, cells = {_R_SP, _R_BP}, set()
    upto = -1

    loads, stores = [], []

    def visit(node):
        nonlocal upto
        a = node.abs
        if a is not None:
            regs.update(a.bases)
            loads.extend(a.loads)
            stores.extend(a.store_regs)
            if node.cond is not None:
                upto = max(upto, node.k)
                # **The registers this decision reads are the ones its FLAGS came
                # from**, which `_abs_step` recorded as `flag_regs` — not every
                # register on the path, and not "the ones that happen to be
                # known". A register that was merely loaded is not in the set
                # unless a decision consults it, which is what keeps the facts
                # small: the stack words a callee loads its ARGUMENTS from are
                # read by no decided condition anywhere on the path.
                regs.update(a.flag_regs)
        for kid in node.kids:
            visit(kid)

    visit(root)
    # **A tracked register's own source cell is tracked too, and that is not
    # tidiness.** A fact states a register's value at every step, and a fact is
    # derived from the previous one; so a register that is unknown at step `k-1`
    # and known at `k` — loaded at `k` from a cell whose value the walk DOES know
    # — leaves the chain a hole unless that cell has a fact too. Measured:
    # `wide_recv` states `s51.rbx = <literal>` where `s50.rbx` is unknown, and
    # `decide` fails on it with "Expected type must not contain free variables".
    # **The two sets are a FIXED POINT, and neither can be had without the
    # other.** A tracked register needs a fact for its own source cell, because a
    # register that is unknown at one step and known at the next is loaded, and
    # a fact reduces one step and hands the rest to the previous fact. A tracked
    # cell needs a fact for the register that was STORED into it, for the same
    # reason — and the register that was stored may be one nothing has tracked
    # yet. Measured on `wide_recv`: `s25.rbp` is right, `s24.rax` is not in any
    # fact, and a cell written from it makes `decide` fail with "Expected type
    # must not contain free variables". Two rounds are not enough in general, so
    # this iterates; it terminates because both sets are finite.
    for _ in range(len(_REG_FIELDS) + 1):
        before = (frozenset(regs), frozenset(cells))
        cells.update(c for r, c in loads if r in regs)
        regs.update(r for r, c in stores if c is not None and c in cells)
        if before == (frozenset(regs), frozenset(cells)):
            break
    return sorted(regs), sorted(cells), upto


def _abs_peel(node, cells):
    """The `rw`s that take THIS step's store off each tracked cell.

    A store is at `(address, value)` — the abstract machine's own record of it —
    and a cell is one of the addresses `_tracked` says a decision may read. Three
    cases, all from the library and all with a side condition Lean can decide,
    because the address is a LITERAL by the time this runs: the store lands
    exactly on the cell (`mem_read_bytes_write_same`, which reads the value back
    and masks it to `lowMask 8`), or it is wholly above the cell
    (`mem_read_bytes_write_above`), or wholly below (`…_below`). A partial
    overlap cannot arise: every store on this path is eight bytes wide, so two
    of them either coincide or are disjoint.

    Nothing is returned for a step that did not store, which is the common case
    on a path: the cell's value is then the previous fact's, verbatim.
    """
    if node.write is None:
        return []
    addr, _val = node.write
    out = []
    for c in cells:
        if addr == c:
            out.append("mem_read_bytes_write_same _ %d _" % c)
        elif addr + 8 <= c:
            out.append("mem_read_bytes_write_above _ %d _ 8 8 %d (by decide)"
                       % (addr, c))
        elif c + 8 <= addr:
            out.append("mem_read_bytes_write_below _ %d _ 8 8 %d (by decide)"
                       % (addr, c))
    return out


def _leaf_halts(node, acc=None):
    """The halt address of every leaf, in the order the walk reaches them.

    One entry per leaf: None for the outermost `ret` (which lands on the exit
    sentinel 0 by popping the zero `X86State.init` leaves on the stack), and the
    `call`'s own address for a leaf that leaves the image (`_tree`'s "leaves").
    `emit_terminates` turns the list into the theorem's disjuncts, one per
    entry, and `_Node.halt` carries each leaf's index — which is why this is a
    pre-pass that ANNOTATES rather than a second traversal the walk has to stay
    in step with.

    The order is the walk's, and it has to be: the statement names the
    disjuncts and the walk picks between them with `left`/`right`, so an index
    computed in a different order is a proof of the wrong disjunct. Every
    branch here is the same recursion `walk` does — `kids[0]` then `kids[1]` at
    a fork — and `walk` reads the index off the node rather than counting.
    """
    acc = [] if acc is None else acc
    if node.kids:
        for kid in node.kids:
            _leaf_halts(kid, acc)
    else:
        node.halt = len(acc)
        acc.append(node.succ)
    return acc


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
    # What the file would COST, refused by name: see `_MAX_CHAIN_STEPS` for the
    # measurement and for why the guard makes it necessary rather than merely
    # prudent. `leaves` is counted because it is the multiplier -- a tree's own
    # node count undercounts by the number of paths through it.
    leaves = list(_paths(root))
    steps = sum(len(p) for p in leaves)
    if steps > _MAX_CHAIN_STEPS:
        raise _NoTree(
            "size",
            "%d step equations over %d leaves, past the %d this emitter can "
            "prove (every branch it cannot settle doubles the paths through "
            "it; the stack-floor guard's own two are settled, so this is the "
            "program's; see _MAX_CHAIN_STEPS)"
            % (steps, len(leaves), _MAX_CHAIN_STEPS))
    # Every node in the tree, which is an upper bound on the length of any one
    # path and so on the depth the closing `simp` at each `ret` will need.  Both
    # arms of a fork are counted, which over-counts; the option is a limit, so
    # over-counting only ever costs headroom nobody uses.
    out = _header(code, insns, base, _nodes(root))
    # **The theorem is a DISJUNCTION, one disjunct per leaf of the tree.**
    #
    # It was a single claim — "the run reaches the exit pc" — and it was
    # correct exactly as long as every path ended at the outermost `ret`. The
    # stack-floor guard put a `call exit(2)` in every prologue of every program
    # image (`_emit_stack_floor_guard`), so now a path can end by reaching a
    # call that leaves the image, and for that path the run does NOT reach the
    # exit pc: the model cannot decode an address outside the image, so
    # `x86_exec_go_exit` returns `none` (`x86_exec_go_exit_stuck`). The old
    # statement is FALSE for it, which is why this could not have been fixed by
    # walking the guard's trap arm — it had to be fixed in what is claimed.
    #
    # What each disjunct claims is what the model supports: the run reaches the
    # halt address that leaf names. `x86_exec_go_exit` tests `st.rip = exit`
    # BEFORE it steps, so naming a call's own address makes the run stop one
    # instruction earlier and the claim becomes "the run REACHES the call" —
    # the arm64 generator's own answer for a call out of the image, in
    # `_call_boundary`'s "opaque" kind and `_gen_universal_e2e_cfg`'s `exit_at`:
    # "the fix is not to admit the `none` branch but to state the theorem the
    # model CAN support, with the call as the halt address".
    #
    # The `none` branch is not an alternative reading, and it is worth saying
    # why rather than leaving it to be re-asked: `(x86_exec_exit …) = none` is
    # implied by `isSome = true`'s negation, so `A ∨ = none` holds for every
    # `Option` and says nothing at all about where the run ended. Fuel
    # exhaustion ends a run with `none` too. Only a NAMED halt address carries
    # information.
    halts = _leaf_halts(root)
    n_disjuncts = len(halts)
    # What the per-step value facts have to state, and how far they run. Both
    # come off the finished tree (`_tracked`), because they are about the whole
    # path and the walk emits them one step at a time.
    regs, cells, upto = _tracked(root)

    def _disjunct(i):
        addr = halts[i]
        if addr is None:
            return ("(x86_exec_exit (X86State.init n %d) rc 0).isSome = true"
                    % entry)
        return ("(x86_exec_go_exit (X86State.init n %d) rc %d 100000).isSome"
                " = true" % (entry, addr))

    # NOT "No `sorry`", which this claimed until `admitted_facts` existed to
    # contradict it: the path tree IS walked once per branch outcome, so the
    # chain is walked, and `wide_recv` then emits four admitted `hpop`s and an
    # admitted closing `hrip` — five holes a reader cannot see from the verdict
    # line, which said "proved, 1 sorry" for all five.  The count is printed
    # beside the verdict now, and it is the number to watch.
    out.append("/-- For EVERY input, the model runs this image to one of %d halt\n"
               "    addresses: the exit sentinel, or a `call` that leaves the image.\n"
               "    The path tree is walked once per branch outcome; the holes this\n"
               "    leaves are named and counted in the report below. -/"
               % n_disjuncts)
    out.append("theorem terminates (n : UInt64) :")
    for i in range(n_disjuncts):
        out.append("    %s%s" % ("∨ " if i else "", _disjunct(i))
                   + ("" if i + 1 < n_disjuncts else " := by"))
    out.append("  rw [x86_exec_exit_eq_go]")
    out.append("  have hb := all_bytes")
    out.append("  let i0 : X86State := X86State.init n %d" % entry)

    # Whether this path has returned out of a callee and back into its caller.
    # Read at the closing `hrip`, where it decides whether the exit-slot read is
    # attempted in full or admitted — see there for why crossing a frame is what
    # makes the difference.
    crossed = [False]

    def walk(node, state, ind, cases, rules, hs_in=None, hs_path=(),
             fs_path=()):
        """Emit one node and, for a branch, both of its children.

        `cases` are the `by_cases`/decided hypotheses in scope at this point;
        `rules` the `x86_exec_go_exit_step` applications that reduce the run so
        far, in order, which is what the closing `rw` replays.

        `fs_path` is the FORM of every step walked so far on this path, and it
        is what sizes a decided branch's `simp`: the set of definitions to
        unfold is read off the path's own instructions rather than passed whole
        (see `_SIMP_FORMS`).
        """
        # The step index is the NODE's, stamped by `_tree`. It used to be a
        # counter kept here, which was a second answer to the same question the
        # build was already answering — and the build is where `_tracked` reads
        # it from, before this walk exists.
        k = node.k
        # A `ret` with a successor is returning into a CALLER; one without is
        # the outermost `ret`, which pops the zero `X86State.init` leaves on the
        # stack and so ends the run at the exit sentinel. `_tree` tells them
        # apart by exactly this, and the difference is the whole of
        # bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md:
        # treating the first as the second is what emitted `s_N.rip = 0` where
        # the machine pops the address the `call` pushed.
        ret_to = node.succ if node.kind == "ret" else None
        nxt = "s%d" % (k + 1)
        pad = "  " * ind
        case_simp = (", " + ", ".join(cases)) if cases else ""

        def emit(line):
            out.append(pad + line if line else "")

        def emit_value_facts(node, name, index, forms):
            """The step's own `hval`, if a decided branch on this path will need it.

            **Why there is a fact per STEP and not one `simp` over the chain.** A
            decision is about `x86_cond cc s{k}`, and `s{k}` is a single nested term
            `s1 = {i0 with …}, s2 = {s1 with …}, …` — so the direct proof is one
            `simp` over every successor equation on the path, and that is what this
            emitter emitted first. It works to about 30 steps and then stops being
            affordable, superlinearly: measured on `wide_recv`, one such `simp` at
            step 41 cost a few seconds and the same one at step 131 was still running
            at `PROOF_WALL_S` (1500 s), with `mem_write_bytes`'s `ite` chain and the
            nested `Int.ofNat … + disp` addresses being re-normalised at every one
            of the 131 levels. The file was 1500 s of wall and then a FAILURE about
            the clock, which is the trade `bugs/FORMAL_x86_64_end_to_end_proof.md`
            calls B21 from the wrong side — a worse report than the refusal it
            replaced.

            So the values are stated ONE STEP AT A TIME instead: `hval{k}` is about
            `s{k}`, and its proof uses `hs{k}` — which describes `s{k}` in terms of
            `s{k-1}` — plus `hval{k-1}`. Each is a projection reduction over one
            record update and the literal arithmetic on the result, so the whole
            chain costs what one step costs times the number of steps. Measured on
            `wide_recv`: the 131 facts plus the decision they feed elaborate in 62 s,
            where the single `simp` they replace did not finish in 1500 s.

            `upto` bounds it: nothing after the last decided branch on the path is
            emitted, and a path with no decided branch emits none at all.
            """
            if index > upto:
                return
            st = node.after
            conj = []
            for r in regs:
                v = st.get(r) if st is not None else None
                if v is not None:
                    conj.append("%s.%s = %d" % (name, _REG_FIELDS[r], v))
            for c in cells:
                v = st.load(c) if st is not None else None
                if v is not None:
                    conj.append("mem_read_bytes %s.mem %d 8 = %d" % (name, c, v))
            if not conj:
                return
            emit("have hval%d : %s := by"
                 % (index, " ∧\n      ".join(conj)))
            # The four accessors are always in: a register read in a successor
            # is `x86_get_reg s{k} (rm + x86_rex_b rex)` until BOTH are reduced,
            # and which of them a given step needs is that step's own row.
            simp = ["hs%d" % index, "hval%d" % (index - 1), "x86_get_reg",
                    "x86_set_reg", "x86_rex_b", "x86_rex_r"]
            simp += [n for n in _SIMP_FORMS.get(forms[-1], ())
                     if n not in ("mem_read_bytes", "mem_write_bytes")]
            emit("  simp [%s]" % ", ".join(dict.fromkeys(simp)))
            # A store at this step is PEELLED off the cells the facts track, with
            # the library's own disjointness lemma and a side condition Lean can
            # decide because the address is a literal by then — which is what one
            # more step of unfolding buys, and what the whole chain would have
            # cost if it were the chain's job.
            peel = _abs_peel(node, cells)
            if peel:
                emit("  <;> rw [%s]" % ", ".join(peel))
                # …and the previous fact AGAIN, because the peel has just
                # produced the read it states: the `simp` above could not use it,
                # since at that point the term was still `mem_read_bytes
                # (mem_write_bytes …)`, and a fact rewrites only the term it is
                # stated about. Emitted ONLY here — a second `simp` with the same
                # set on a goal the first one already closed is a "simp made no
                # progress" error, which is the same shape as a fact that says
                # nothing.
                emit("  <;> simp [hval%d]" % (index - 1))
            emit("  <;> decide")


        def emit_disjunct(i):
            """Pick disjunct `i` of the statement: `right` past each one above.

            `A ∨ (B ∨ (C ∨ D))` — `∨` binds to the right, so `D` is three
            `right`s and NO `left`, while B is one `right` and a `left`. There
            is no `Or` sugar in tactic mode; `left` and `right` are the tactics
            that build one, and `left` on the last disjunct is the failure this
            docstring's first sentence exists to describe. The index
            `_leaf_halts` put on the node is all this needs, which is the point
            of putting it there.
            """
            for _ in range(i):
                emit("right")
            if i + 1 < n_disjuncts:
                emit("left")

        if node.kind == "leaves":
            # **The leaf that leaves the image, and it emits NO step.** The run
            # is AT the call and the halt address is the call's own address, so
            # the closing `x86_exec_go_exit_at` fires on the state this node was
            # reached in — stepping the call would move `rip` to the callee, and
            # the model's runner would then have no instruction to step there.
            #
            # The `rip` fact is a literal in the predecessor's successor
            # equation (`hs_in`), which is why this arm is CHEAP where the exit
            # leaf is not: there is no memory read here to reconstruct, so it is
            # `simp only [hs{k}]` and no admission. That is the whole reason the
            # guard's trap arm is affordable at all — see the statement's own
            # comment for what it claims.
            emit_disjunct(node.halt)
            emit("have hhalt%d : %s.rip = %d := by" % (k, state, node.addr))
            emit("  simp only [%s]" % ("i0, X86State.init" if hs_in is None
                                       else hs_in))
            emit("rw [%s]" % ",\n    ".join(
                rules + ["x86_exec_go_exit_at (by decide) hhalt%d" % k]))
            emit("simp")
            return

        call, succ = _resolve(node.form, node.raw, node.addr, state, k,
                              cases, hs_in, node.insn.length,
                              rip=ret_to)

        if ret_to is not None:
            # The chain has crossed a FRAME boundary, which is what the closing
            # read below has to know: see the `hrip` block.
            crossed[0] = True
            # **The popped return address, as its own named fact.** The step
            # below is still the model's `x86_step_ret`; this supplies the one
            # field the tree knows and the model reads out of memory, and `rw`
            # puts it in, after which every later step sees an ordinary literal
            # `rip` and the chain carries on into the caller.
            #
            # The proof is the doc's option 2 and it is deliberately the CHEAP
            # one: `simp only [hs{k}]` peels the single successor equation that
            # writes memory and leaves `(mem_read_bytes …) = <literal>`
            # unsolved, which the guard admits. The expensive alternative --
            # `simp` over every equation on the path, which is what the closing
            # `hrip` does -- exhausts the 4 000 000 heartbeat budget in 110 s on
            # `wide_recv`, and a heartbeat timeout is NOT catchable by `try`, so
            # it would take the whole file down rather than admitting one fact.
            # What this buys is a theorem stated over a chain that runs to the
            # exit instead of one that stops at a return it must not stop at.
            #
            # What it costs needs saying precisely, because the REPORT does not
            # say it: Lean reports "declaration 'terminates' uses 'sorry'" once
            # per declaration and `formal/lean.py::_census_from_output`
            # de-duplicates by name, so a chain with four admitted `hpop`s reads
            # as `proved, 1 sorry` exactly like one with a single gap in it.
            # The number is a bound and not a count of holes (which is what
            # bugs/FORMAL_x86_64_end_to_end_proof.md concluded about it
            # independently), and these holes are countable by NAME in the
            # generated file: `hpop{k}`, one per returned-to. Closing them is the
            # per-step separation invariant the bug doc names as the remaining
            # work.
            emit("have hpop%d : (mem_read_bytes %s.mem (%s.rsp.toNat) 8).toNat"
                 " = %d := by" % (k, state, state, ret_to))
            emit("  simp only [hs%d]" % k)
            emit("  all_goals sorry")
        emit("have hstep%d : x86_step %s rc = some %s := by"
             % (k, state, succ) if ret_to is not None
             else "have hstep%d : x86_step %s rc = some %s :="
             % (k, state, succ))
        if ret_to is not None:
            # An explicit `by`, and the rewrite in the direction that makes the
            # lemma apply. Two things, both found by running it:
            #
            #  * `have h : T :=` followed by two indented lines parses the
            #    second as a TERM, so `rw [hpop157]` reads as an unknown
            #    identifier applied to the lemma — `error: Unknown identifier
            #    'rw'`, which says nothing about the return. Hence `by`.
            #  * the rewrite goes `←`. The successor already carries the literal
            #    (that is what `rip=ret_to` put there), so `rw [hpop{k}]` finds
            #    no occurrence of the read to replace; what has to happen is the
            #    literal going BACK to the model's `(mem_read_bytes …).toNat` so
            #    that `x86_step_ret`'s own conclusion matches. So the step is
            #    still proved by the model, and the tree's knowledge enters as the
            #    one rewrite that says the two are the same word.
            emit("  rw [← hpop%d]" % k)
        emit("  " + ("exact " if ret_to is not None else "") + call)
        emit("obtain \u27e8%s, h%d\u27e9 : \u2203 t, x86_step %s rc = some t :="
             % (nxt, k, state))
        emit("  \u27e8_, hstep%d\u27e9" % k)
        emit("have hs%d : %s = %s := by" % (k + 1, nxt, succ))
        emit("  rw [h%d] at hstep%d" % (k, k))
        emit("  exact Option.some.inj hstep%d" % k)
        emit_value_facts(node, nxt, k + 1, fs_path + (node.form,))
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
            both = rules + [step_rule]
            if node.cond is None:
                emit("by_cases hc%d : x86_cond %d %s = true" % (k, cc, state))
                emit("\u00b7")
                walk(node.kids[0], nxt, ind + 1, cases + ["hc%d" % k], both,
                     "hs%d" % (k + 1), hs_path + ("hs%d" % (k + 1),),
                     fs_path + (node.form,))
                emit("\u00b7")
                walk(node.kids[1], nxt, ind + 1, cases + ["hc%d" % k], both,
                     "hs%d" % (k + 1), hs_path + ("hs%d" % (k + 1),),
                     fs_path + (node.form,))
                return
            # **THE DECIDED ARM, and it is emitted as a PROOF.**  `_tree` settled
            # this condition from the abstract machine, so only one arm was built
            # and only one arm is emitted; what says the other arm is unreachable
            # is this fact, and it is proved.
            #
            # There is no `try` and no `sorry` anywhere in it, and that is the
            # whole safety argument for having a static analysis at all: a
            # decision the abstract machine gets WRONG leaves a goal that is
            # false, and Lean rejects the file. It cannot become a `sorry` on a
            # side condition and a claim about the machine's future at once, so
            # the emitter cannot quietly start proving things that are not true.
            #
            # `hs_path` alone: it already ends at `hs{k}`, the equation that
            # describes `state` — the state the goal names — because the tail
            # call above appended it before recursing. `hs{k+1}` describes the
            # SUCCESSOR, which is emitted after this and is not in scope here.
            emit("have hdec%d : x86_cond %d %s = %s := by"
                 % (k, cc, state, "true" if node.cond else "false"))
            # The forms that size this `simp` are the FLAG SETTER's, not the
            # branch's: `hs{k}`'s right-hand side is a record whose `zf`/`cf`
            # fields are `(x86_flags_sub s{k-1} …).zf`, so without the setter's
            # own definitions the goal stops at exactly that — measured, and the
            # fix is one entry of the form table away.
            emit("  simp [%s]" % _decision_simp(
                fs_path[-1:], ["hs%d" % k, "hval%d" % (k - 1)] if k else ["i0"]))
            emit("  <;> decide")
            # …and the hypothesis joins the `simp` sets below, exactly as a
            # `by_cases` hypothesis would: the successor's `rip` is an `if` on
            # this very condition, and without it every later step on this path
            # would be proving an `if`.
            walk(node.kids[0], nxt, ind, cases + ["hdec%d" % k], both,
                 "hs%d" % (k + 1), hs_path + ("hs%d" % (k + 1),),
                 fs_path + (node.form,))
            return

        if node.kind == "ret" and node.succ is None:
            emit_disjunct(node.halt)
            # The OUTERMOST return, and the only place the exit sentinel is
            # read: `X86State.init` leaves the stack zeroed, so this `ret` pops
            # address 0 and `x86_exec_go_exit` stops there. A `ret` with a
            # successor does not come here — it has already emitted its `hpop`
            # above and recurses into the caller below.
            #
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
            if crossed[0]:
                # **A chain that came back through a `ret` cannot afford the
                # closing `simp`, and the admission is the honest answer.**
                #
                # The block below proves `s.rip = 0` by unfolding EVERY successor
                # equation on the path at once, with `x86_set_reg` and
                # `x86_get_reg` in the set so that the register-derived write
                # addresses reduce. Measured on the 45-example corpus that is
                # 93 s for `wide_recv`'s 40-step chain — and the chain that
                # follows the return is 112 steps, because the caller's
                # continuation is now part of it and the register file has to be
                # reconstructed across the frame boundary. At 112 it does not
                # finish: 1190 s of wall and then `(deterministic) timeout at
                # `whnf``, which is B21's lesson arriving from the other side —
                # an unaffordable attempt reported as a FAILURE is worse than an
                # admitted gap, because the failure is 20 minutes that say
                # nothing and the gap is one number.
                #
                # So the crossing is what selects the treatment, and it is a
                # fact about the PATH rather than a guess about its size: a
                # chain that never left its own frame has one frame's worth of
                # register file to reduce, and one that has is the case the
                # attempt is not for. What is admitted here is exactly the
                # separation fact, and the report counts it like any other.
                emit("  simp only [hs%d]" % (k + 1))
                emit("  all_goals sorry")
                full = rules + [step_rule,
                                "x86_exec_go_exit_at (by decide) hrip"]
                emit("rw [%s]" % ",\n    ".join(full))
                emit("simp")
                return
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
             "hs%d" % (k + 1), hs_path + ("hs%d" % (k + 1),),
             fs_path + (node.form,))

    if upto >= 0:
        # `hval0`: the initial state's own field values, which is where the whole
        # chain of `hval`s bottoms out. This is the ONE place `mem_read_bytes` is
        # unfolded on purpose — `X86State.init`'s memory is `fun _ => 0`, so the
        # cell facts the decisions need start here as literals rather than as
        # reads.
        conj = ["i0.%s = %d" % (_REG_FIELDS[r], v)
                for r in regs if (v := _INIT_FACTS.get(r)) is not None]
        conj += ["mem_read_bytes i0.mem %d 8 = 0" % c for c in cells]
        out.append("  have hval0 : %s := by" % " ∧\n      ".join(conj))
        out.append("    simp [i0, X86State.init, x86_get_reg, mem_read_bytes]")
        out.append("    <;> decide")

    walk(root, "i0", 1, [], [], None, (), ())
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


#: A NAMED fact whose proof this emitter ADMITTED rather than closed:
#: `have <name> … := by`, followed — inside its body — by a `sorry`.
#: `have <name> … :=` — with or WITHOUT a `by`.  Both spellings open a proof, and
#: the one without matters: every step lemma is emitted as
#:     have hstep7 : x86_step s6 rc = some { … } :=
#:       x86_step_leave s6 rc … (by try (…) <;> all_goals sorry) …
#: so requiring `by` left `cur` on the PREVIOUS fact and charged every guarded
#: side condition to it — 118 named holes on `wide_recv` where there are 9, every
#: `hs` and `hstep` in the chain wrongly named as an admission.
_HAVE_BY = re.compile(r"^\s*have\s+([A-Za-z_][A-Za-z_0-9']*)\b.*:=")
#: A `sorry` as a tactic.  Matching the bare word would also count the word in
#: a comment, and the generated text carries comments.
_SORRY = re.compile(r"\b(?:all_goals\s+)?sorry\b")
#: …and one on a line of its OWN, which is the shape the emitter writes when it
#: has given up on a fact:
#:     have hpop3 : … := by
#:       simp only [hs3]
#:       all_goals sorry
#: The inline form — `(by try (…) <;> all_goals sorry)` — is a GUARD, and is a
#: different fact entirely: the tactic is attempted first and the `sorry` is
#: reached only if it does not close the goal. Whether it fired is known only to
#: Lean, and Lean does not say, so counting the inline form as a hole
#: OVER-counts (measured: 118 "admissions" on `wide_recv` where there are 5) and
#: not counting it UNDER-counts. They are reported as two numbers because they
#: are two facts, which is B21's whole subject.
_SORRY_ALONE = re.compile(r"^\s*(?:all_goals\s+)?sorry\s*$")
#: A `/- … -/` block comment, replaced by blank lines so the line numbers the
#: check reports still point at the source.
_BLOCK_COMMENT = re.compile(r"/-.*?-/", re.S)
#: The guard's own shape, so a guarded side condition is counted rather than
#: lumped in with an admission.
_GUARD = re.compile(r"\(\s*by\s+try\b")


def admitted_facts(text):
    """`[(name, line, kind)]` for every way this file's proof is short of closed.

    `kind` is `"admitted"` or `"guarded"`, and the two are counted separately by
    every caller because they answer different questions:

      `admitted`  the emitter WROTE `all_goals sorry` as a fact's whole proof.
                  A hole, always. Nothing was attempted.

      `guarded`   a side condition written `(by try … <;> all_goals sorry)`. The
                  tactic runs first; the `sorry` is reached only if it does not
                  close the goal. So this is a fact about the EMISSION, not
                  about the proof: the fact may be fully proved and Lean says
                  nothing either way, because it reports "declaration 'terminates'
                  uses 'sorry'" once per DECLARATION and
                  `formal/lean.py::_census_from_output` de-duplicates by name.
                  A chain with four admitted `hpop`s and one with a single gap
                  read identically — `bugs/FORMAL_x86_64_end_to_end_proof.md`
                  reaches the same conclusion about `augassign` from the other
                  end, and this is a statement about the CENSUS rather than the
                  proof.

    Counted off the generated TEXT rather than kept in a counter beside it, for
    the reason the rest of this file's numbers are: a tally maintained next to
    the emitter is a second source of truth for what was emitted, and the first
    thing to go wrong when one changes is the tally. A `sorry` reached before
    any `have` is reported under `_body`, so it cannot go missing.
    """
    out = []
    cur = None
    # Comments first, and BOTH forms: the generated file carries `/- … -/`
    # docstrings whose prose names the thing being counted ("No `sorry`: …"), and
    # a `--`-only filter charged the theorem's own docstring as an admission —
    # reported as `_body`, which is precisely the "a check that cannot fail is
    # green" shape this is meant to remove.
    body = _BLOCK_COMMENT.sub("", text)
    for n, line in enumerate(body.split("\n"), start=1):
        if line.lstrip().startswith("--"):
            continue
        m = _HAVE_BY.match(line)
        if m:
            cur = (m.group(1), n)
        if _SORRY_ALONE.match(line):
            out.append((cur if cur is not None else ("_body", n), "admitted"))
        elif _SORRY.search(line):
            kind = "guarded" if _GUARD.search(line) else "admitted"
            out.append((cur if cur is not None else ("_body", n), kind))
    return [(nm, ln, kind) for (nm, ln), kind in out]


def _run_lean(text):
    """`(ok, n_sorries, first_error)` for one generated Lean file.

    `n_sorries` is `admitted_facts`' count — the holes THIS emitter opened —
    and not Lean's `declaration uses 'sorry'` line count. Both are called a
    "sorry" and they are not the same number; see `admitted_facts` for why the
    one Lean reports cannot be used here. Lean's is kept as a cross-check that
    the two do not DISAGREE, because they must: a `sorry` this emitter did not
    write would mean a library hole had leaked into a generated file, and a
    count of zero with Lean's non-zero is that.
    """
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
        sorries = sum(1 for _n, _l, k in admitted_facts(text)
                      if k == "admitted")
        if not errs:
            lean_sorries = sum(1 for l in out.splitlines()
                               if "declaration uses" in l)
            if lean_sorries and not sorries:
                errs.append(
                    "Lean reports %d declaration(s) using `sorry` and this "
                    "emitter admitted no fact of its own: a library hole has "
                    "leaked into a generated file, and counting only ours "
                    "would have reported it as clean" % lean_sorries)
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
    val_holes = []
    fails = notree = noform = nocall = nosize = hole_total = guard_total = 0
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
                val_holes = sorted({n for n, _l, k in admitted_facts(
                    emit(t, expected)) if k == "admitted"})
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
                vs = "  value:     rax = %d, every input, %d admitted (%s)" % (
                    expected, val_sorries, ", ".join(val_holes) or "none")
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
            text = emit_terminates(t)
            ok, sorries, err = _run_lean(text)
            # The NAMES, not just the number, because the number alone cannot be
            # acted on: `admitted_facts`' docstring has the measurement that Lean
            # reports one line per DECLARATION, so four `hpop`s read as one gap.
            facts = admitted_facts(text)
            holes = sorted({n for n, _l, k in facts if k == "admitted"})
            guarded = sum(1 for _n, _l, k in facts if k == "guarded")
        except ValueError as exc:
            # Three reasons a path cannot be built, kept apart for B21's reason,
            # plus the fourth kind the `_NoTree` docstring is about.  `_has_loop`
            # is asked LAST because a path that returns into a caller can also
            # contain a loop, and "loops" would then be the wrong reason -- the
            # run reaches rip = 0 nowhere on that path either way, but only one
            # of them is what stopped the walk.
            if isinstance(exc, _NoTree):
                kind, detail = exc.kind, str(exc)
            elif _has_loop(t):
                kind, detail = "loops", ""
            else:
                kind, detail = "form", str(exc)
            if kind == "loops":
                notree += 1
            elif kind == "call":
                nocall += 1
            elif kind == "size":
                # A fourth counter rather than a fourth spelling of one of the
                # others, for the reason the other three have: a tree that is
                # refused for being unaffordable is not a form with no lemma,
                # and folding it into `noform` would put a row about an
                # unmodelled instruction where the problem is the clock.
                nosize += 1
            else:
                noform += 1
            ts = _no_tree_line(kind, detail)
        else:
            if ok and not sorries:
                term_ok += 1
                ts = "  terminates: PROVED"
            elif ok:
                term_gap += 1
                hole_total += sorries
                guard_total += guarded
                ts = "  terminates: proved, %d admitted (%s), %d guarded" % (
                    sorries, ", ".join(holes) or "unattributed", guarded)
            else:
                fails += 1
                ts = "  terminates: FAIL %s" % err.strip()[:60]
        print("%-14s%s\n%s" % (name, vs, ts))

    print("\n  value      : %d proved with no sorry, %d open"
          % (val_ok, val_gap))
    print("  terminates : %d proved with no sorry, %d proved with a sorry"
          % (term_ok, term_gap))
    # What the sorry COUNT is, since it is not Lean's and the two disagree: these
    # are the holes THIS emitter opened, counted off the generated text by the
    # name the emitter gave them. `admitted_facts` has why Lean cannot supply it.
    print("               %d admitted fact(s) and %d guarded side condition(s) "
          "in the proved-with-a-sorry files, counted by name from the generated "
          "text" % (hole_total, guard_total))
    print("               %d no finite tree (%d loop, %d uncovered form, "
          "%d returns into a caller, %d too large to prove)"
          % (notree + noform + nocall + nosize, notree, noform, nocall, nosize))
    print("  failing    : %d" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
