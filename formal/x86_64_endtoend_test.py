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

    * A path that RETURNS INTO A CALLER used to be declined, and it was the one
      limit here that was not a gap in the proof but a falsehood in it.  `call`
      pushes a return address and `ret` pops one, so a function that calls
      another does not finish where the callee finishes; the tree used to make
      every `ret` the end of the run, the chain stopped at the callee's return,
      and the closing `hrip : s_N.rip = 0` claimed the exit sentinel where the
      machine has the address after the `call`.  The return is followed now
      (`_tree`, B26) and the read at each followed return is PROVED rather than
      admitted (`_concrete_read`): the popped address is a closed term, so the
      proof evaluates it instead of simplifying it into one.  What it cost when
      it was admitted is in
      `bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`,
      which is where the boundary and the measurement behind the fix both live.


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
    # Each side condition is a `try (<attempt>)` and then an `all_goals sorry`
    # ON ITS OWN LINE, so one that does not go through is admitted rather than
    # fatal, and Lean reports the file as using `sorry`.
    #
    # Three things about that shape, all learned the hard way here, and the
    # third is the one that was wrong for as long as it was written down.
    #
    #  * The guard must be INSIDE the inline `by`: an unsolved goal inside
    #    `(by simp [hs12])` is an ELABORATION error, not a tactic failure, so
    #    neither an enclosing `try` nor `first | exact ... | sorry` around the
    #    whole step catches it and the file dies.
    #  * It must not be `first | simp ... | all_goals sorry`: `first` commits to
    #    the first alternative that does not THROW, not the first that closes the
    #    goal, so a `simp` that runs and simplifies nothing is taken as a
    #    success and the `sorry` alternative is never reached.
    #  * **And the `all_goals sorry` must NOT be chained with `<;>`.** It was,
    #    for every side condition in every generated file, on the strength of
    #    B23's second point -- and `try t1 <;> t2` does not run `t2` when `t1`
    #    throws. Measured, on the two-line form and the chained form of the same
    #    guard over the same unsatisfiable goal:
    #
    #        exact (by try (first | native_decide | decide) <;> all_goals sorry)
    #          -> `unsolved goals ... ⊢ a + 1 = 4`, and the file dies
    #        exact (by
    #          try (first | native_decide | decide)
    #          all_goals sorry)
    #          -> `declaration uses sorry`, and the file builds
    #
    #    So the guard never admitted anything: it reported the hole as a build
    #    failure instead, which is the exact failure B23 exists to prevent and
    #    which it was introduced to fix. It stayed hidden because no side
    #    condition in the corpus FAILED -- every one of the 542 guarded facts in
    #    the 24-argument program closes -- so the broken arm was never taken, and
    #    `terminates proved with no sorry` could not tell the difference. The
    #    first guard that can fire is `_concrete_read`'s, which is why the two
    #    had to be fixed together.
    #
    # This is what let `imul` mask an unrelated gap in the `rsp + disp8` load:
    # 8 examples read "no tree" instead of "tree, one step unproved".
    def sc_(tactic):
        return "(by\n  try (%s)\n  all_goals sorry)" % tactic

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

    `halt` is set by `_leaf_halts` and is the index of this leaf's disjunct in
    `emit_terminates`' statement, or None for a node that is not a leaf. It
    lives on the node rather than in a counter beside the walk so the two
    traversals cannot come to disagree about which leaf is which: the statement
    is written before the walk runs, so it has to know the leaves in advance,
    and two counters incremented in step are two answers to one question.
    """
    __slots__ = ("insn", "form", "raw", "addr", "kind", "state", "succ", "kids",
                 "halt")

    def __init__(self, insn, form, raw, addr, kind, state, succ):
        self.insn, self.form, self.raw, self.addr = insn, form, raw, addr
        self.kind, self.state, self.succ = kind, state, succ
        self.kids = []
        self.halt = None


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
    """
    base, entry = info["base_addr"], info["func_offset"]
    by_addr = {base + i.offset: (i, f, r) for i, f, r in shapes}
    deep = max(256, sys.getrecursionlimit() - 200)

    def build(addr, state, depth, seen, rets):
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
            taken = build(addr + n + off, None, depth + 1, seen, rets)
            fell = build(nxt, None, depth + 1, seen, rets)
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
            node.kids = [build(addr + off, None, depth + 1, seen, rets)]
            return None if node.kids[0] is None else node
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
                return node
            node = _Node(insn, form, raw, addr, "jmp", state, target)
            node.kids = [build(target, None, depth + 1, frozenset(),
                              rets + (addr + 5,))]
            return None if node.kids[0] is None else node
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
                kid = build(rets[-1], None, depth + 1, seen, rets[:-1])
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
                return node
            return _Node(insn, form, raw, addr, "ret", state, None)
        node = _Node(insn, form, raw, addr, "seq", state, addr + insn.length)
        node.kids = [build(addr + insn.length, None, depth + 1, seen, rets)]
        return None if node.kids[0] is None else node

    try:
        root = build(entry, "i0", 0, frozenset(), ())
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
#: (1500 s) with room, and 4.4x the worst tree in the corpus that is not
#: `wide_recv`.
#:
#: **`wide_recv` is what the bound is for, and the reason is a rule rather than a
#: number.** The stack-floor guard puts two conditional branches in every
#: prologue, and a path tree walks every branch outcome, so the file is
#: `2^(branches on the path)` times what it was: `wide_recv`'s five functions
#: take it from one path to 94. Attempting that costs 1500 s of wall and then
#: reports a FAILURE whose message is about the clock, which is B21's lesson
#: arriving from the other side -- "an unaffordable attempt reported as a
#: FAILURE is worse than an admitted gap, because the failure is 20 minutes that
#: say nothing and the gap is one number". So the tree is refused, BY NAME and
#: with its size in the line, which is what the gap is.
#:
#: **The fix that makes this bound unnecessary is not a bigger bound.** It is for
#: the emitter to decide the guard's own two branches statically rather than walk
#: both arms: they are decided by facts the emitter can compute (the floor word
#: is 0 in `X86State.init`'s memory, so the first `JNE` is not taken; and the
#: stack pointer is a sum of literal frame sizes, so the `JAE` is taken whenever
#: the path is inside `model.STACK_FLOOR_BUDGET_BYTES`). See
#: `bugs/FORMAL_x86_64_the_stack_floor_guards_exit_call_leaves_the_image.md` §
#: "what is left", which is where that is written down with its two Lean
#: obligations.
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


#: The five `lib/X86.lean` lemmas that say a state-valued wrapper leaves memory
#: alone, named here because this is the one consumer that needs them.  See the
#: section "A register write does not change memory" in that file for why they
#: exist at all and why they are not `@[simp]`.
_MEM_LEMMAS = ("x86_set_reg_mem", "x86_set_xmm_mem", "x86_flags_logic_mem",
               "x86_flags_add_mem", "x86_flags_sub_mem")

#: The five state-valued wrappers' DEFINITIONS, which the same file needs
#: unfolded for a different projection.  `_MEM_LEMMAS` gets `.mem` through a
#: wrapper without unfolding it, which is cheaper; but a REGISTER read out of a
#: wrapper's result is a projection the simplifier can only reduce if the
#: wrapper is a constructor in the term, and it is not until it is unfolded.
#: So a write address like `(Int.ofNat (x86_get_reg s (5 + x86_rex_b 0x48)).toNat
#: + -8).toNat` -- every frame-relative store and load this backend emits -- needs
#: all three steps: `x86_rex_b` decoded, `x86_get_reg`'s `match` reduced to one
#: arm, and the wrapper unfolded so the selected field projects.
#:
#: **These are names in a `simp only` set and nothing else.** The whole point of
#: the route is that the simplifier UNFOLDS structure and `native_decide`
#: EVALUATES arithmetic; the old closing block handed the same definitions to a
#: full `simp`, which also ran the default set over every register's arithmetic,
#: and that is the 1190 s the bug doc measured. Nothing here decides an
#: inequality or folds a literal.
_WRAPPER_DEFS = ("x86_get_reg", "x86_set_reg", "x86_set_xmm", "x86_mem_addr",
                 "x86_flags_logic", "x86_flags_add", "x86_flags_sub")


def _rex_byte_lemmas(shapes):
    """The `[simp]` REX decodings for the bytes that actually occur on a path.

    `lib/X86.lean` states all sixteen REX bytes' `w`/`r`/`b` decodings as proved
    `[simp]` facts, and `simp only` does not use the default set, so they have to
    be named. Naming all forty-eight would work and would also print a linter
    warning for each of the forty-odd that no chain uses; naming the ones the
    path contains keeps the set to what the term can mention. A REX byte outside
    `0x40..0x4f` is not a REX byte, and one inside has all three lemmas.
    """
    used = {b for _i, _f, raw in shapes for b in raw if 0x40 <= b <= 0x4F}
    return tuple("x86_rex_%s_%02x" % (bit, b)
                 for b in sorted(used) for bit in ("w", "r", "b"))


def _unfold(hs_path, rex=()):
    """The `simp only` set that replaces a state variable by the term it is.

    `hs{k} : s{k} = <the model's successor for step k>`, and `i0` is the entry
    state, so `hs1 .. hs{k}` plus `i0` describe `s{k}` completely: after
    `simp only` with this set a state PROJECTION is a closed term, and only
    the projections the goal actually mentions have been computed.  `hs_path` is
    the walker's own list, which at node `k` is exactly `hs1 .. hs{k}` and is
    empty only for the first step -- where `i0` alone is the whole chain.

    **The two projection lemmas at the end are what make the result CLOSED**,
    and they are not tidiness. `x86_set_reg` and `x86_set_xmm` are the only two
    functions in `lib/X86.lean` that return a state through a `match`, so a
    `.mem` projection stops there and drags the sixteen register fields with it
    -- one of which is `rdi`, where `X86State.init` puts the program's input.
    `native_decide` refuses a term with a free variable in it, so without them
    the evaluation is refused on any chain long enough to contain a register
    write: measured on `const2`, a 16-step chain whose read is at the initial
    stack and whose answer is 0. `x86_set_reg_mem` says the memory is unchanged
    without unfolding the `match`, and the projection walks on down.
    """
    return ", ".join(("i0, X86State.init",) + tuple(hs_path)
                     + _MEM_LEMMAS + _WRAPPER_DEFS + tuple(rex))


#: **How many successor equations the closing read may UNFOLD, and why it is a
#: number and not an always.**
#:
#: The evaluation is right and it is affordable at the sizes the corpus has --
#: but "the sizes the corpus has" is doing real work in that sentence, and
#: measured the other way round the cost is not affordable: what the read costs
#: is the SIZE OF THE UNFOLDED CHAIN, once per fact, and at the length a call
#: with a stack argument produces the file stops elaborating altogether.
#:
#: Measured, one program at a time, each under `tools/memslot.py` with the
#: generated file exactly as emitted (the number is the largest `simp only` set
#: in the file, i.e. the longest path's closing read):
#:
#: | fixture | longest unfold | wall | peak | verdict |
#: |---|---|---|---|---|
#: | `const2` | **19** | 3.9 s | 1.4 GB | `rc=0`, and the read is CLOSED: with the two `hrip` admissions deleted the file still checks |
#: | a 3-argument call | 77 | 127.3 s | 5.2 GB | `rc=0`, but a `sorry` is still live -- the evaluation did not go through |
#: | an 8-argument call | 113 | 222.6 s | 6.5 GB | **`rc=-6`**: `lean::memory_exception`, `excessive memory consumption detected at 'interpreter'` |
#: | a 24-argument call | 184 | 258.8 s | 6.0 GB | the same abort, and the PRE-CHANGE emitter aborts on it too |
#:
#: So the boundary is between 19 and 77 for "the evaluation closes the read" and
#: between 77 and 113 for "the file elaborates at all", and 64 is inside both
#: gaps. **It is an interpolation and not a crossover measurement**: the exact
#: point was not found, and a reader who wants it should bisect
#: `w3np`/`w8np` rather than trust the number. What the number is FOR is that a
#: chain past it keeps the pre-change shape, which is measured to check --
#: `rc=0`, 225.5 s, 6.0 GB on the 8-argument fixture -- and a hole is a better
#: outcome than an elaboration that never finishes, because it is countable.
#:
#: The fix that makes this constant unnecessary is the per-step separation
#: invariant `bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`
#: names: one cheap fact per step, so the read costs O(1) in the chain's length
#: instead of O(length) once per crossing. That needs an emitter-side
#: stack/frame tracker to make each write's address a literal, and it is not
#: landed.
_MAX_UNFOLD = 64


def _concrete_read(hs_path, rex=()):
    """The two lines that ATTEMPT a memory read out of a CONCRETE state.

    **This is the fix for the boundary
    `bugs/FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`
    names, and it is a change of what gets EVALUATED rather than of what gets
    simplified.**  The read at a `ret` -- the popped return address when it
    returns into a caller, the zero `X86State.init` leaves on the stack when it
    does not -- is `(mem_read_bytes s{k}.mem (s{k}.rsp.toNat) 8)`, and the doc's
    measurement was that going after it with the simplifier costs more than
    1500 s of wall and does not finish: `s{k}.mem` is a `mem_write_bytes` chain
    one link per instruction of the path, every link's ADDRESS is an expression
    in an earlier `s`, and `simp` reduces all of it symbolically.  The emitter
    knows, however, that every address on the path is a literal:
    `X86State.init` gives `rsp` the literal `0xfffffffffffffff0`, and every
    instruction this backend emits that writes memory addresses it through `rsp`
    or `rbp`, both of which are literal sums of literal frame sizes from there.
    So the term is CLOSED, and `native_decide` compiles and evaluates it -- which
    is linear in the chain instead of exponential in it, and does not care how
    the address got to be a literal.

    So this is not "a bigger budget" and not "the same proof, split differently":
    it replaces a simplification that cannot be paid for with an evaluation that
    can.

    **The caller supplies the `all_goals sorry`**, so this is an ATTEMPT and not
    a whole proof: the closing read also has the memory-separation peel as a
    second, more expensive attempt for a chain whose term is not closed, and
    where there is no peel (`hpop`, and a closing read on a chain that crossed
    a frame -- the peel is measured unaffordable there) this is the only one.

    **And past `_MAX_UNFOLD` it is not attempted at all**, which is a bound and
    not a preference -- see that constant's own table for the three measurements
    it is the interpolation of, and for what happens on the wrong side of it.

    `hs_path` is the walker's own list of the successor equations in scope,
    which must include the equation for the state the GOAL is about: at the
    closing `hrip` that is `hs{k+1}` (the state after the outermost `ret`), not
    `hs{k}`, and the site passes the list with that one appended.  Getting it
    wrong is not a wrong proof, it is a `simp` that makes no progress and an
    error -- so the `simp` is `try`-guarded and the fact is admitted, which is
    the same treatment every other attempt in this emitter gets.
    """
    if len(hs_path) > _MAX_UNFOLD:
        # The single equation that writes memory, and no evaluation: this is the
        # shape the emitter used before `_concrete_read` existed, it costs one
        # `simp` whatever the chain's length, and the guard admits the rest. It
        # is what keeps a long chain CHECKED rather than unaffordable, which is
        # the whole difference between a hole and an aborted elaboration.
        return ["  try (simp only [%s])" % hs_path[-1]]
    return ["  try (simp only [%s])" % _unfold(hs_path, rex),
            "  try (first | native_decide | decide)"]


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
           # The closing read's `simp only` set names every REX decoding the
           # body's bytes can call for and every wrapper the successor table
           # quotes, and a chain that mentions none of some of them is the norm
           # rather than the exception -- so `unusedSimpArgs` would print a
           # warning per unmentioned name, hundreds of them, and say nothing.
           # This is the emitter's own emission being deliberately a superset;
           # a genuine unused simp argument inside `lib/` is still reported,
           # because the option is scoped to this file.
           "set_option linter.unusedSimpArgs false\n",
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
            "prove (the stack-floor guard doubles every path; see "
            "_MAX_CHAIN_STEPS)" % (steps, len(leaves), _MAX_CHAIN_STEPS))
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

    # The REX decodings the closing reads' `simp only` sets have to name, from
    # the bytes of the instructions ON THE PATH -- which is every decoded
    # instruction of the body, since `insns` is the body and `shapes` is its
    # decode. Computed once and closed over: the set is the same for every fact
    # in the file, and recomputing it per fact would be the kind of per-fact
    # bookkeeping this file's other numbers exist to avoid.
    rex = _rex_byte_lemmas(shapes)

    counter = [0]
    # Whether this path has returned out of a callee and back into its caller.
    # Read at the closing `hrip`, where it decides whether the exit-slot read is
    # attempted in full or admitted — see there for why crossing a frame is what
    # makes the difference.
    crossed = [False]

    def walk(node, state, ind, cases, rules, hs_in=None, hs_path=()):
        """Emit one node and, for a branch, both of its children.

        `cases` are the `by_cases` hypotheses in scope at this point; `rules`
        the `x86_exec_go_exit_step` applications that reduce the run so far, in
        order, which is what the closing `rw` replays.
        """
        k = counter[0]
        counter[0] = k + 1
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
            # generated file: `hpop{k}`, one per returned-to.
            emit("have hpop%d : (mem_read_bytes %s.mem (%s.rsp.toNat) 8).toNat"
                 " = %d := by" % (k, state, state, ret_to))
            for line in _concrete_read(hs_path, rex):
                emit(line)
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
            # **ONE closing read, two attempts, and the order is the cheap one
            # first.**  `_concrete_read` EVALUATES the closed term; the block
            # after it SIMPLIFIES the same read into a closed term with the
            # memory-separation peel.  They are two routes to one goal and the
            # emitter used to have only the second, which is why:
            #
            #  * on a chain that CROSSED a frame the peel was measured
            #    unaffordable -- 93 s for `wide_recv`'s 40-step chain, and at the
            #    112 steps a followed return makes it does not finish at all
            #    (1190 s, then a heartbeat timeout, which is NOT catchable by
            #    `try`), so that path could only be admitted; and
            #  * on a chain that did not, the peel left a hole on its own: the
            #    `const2` control closed as `proved, 1 admitted (hrip)` with
            #    every one of its 251 side conditions proved, because the read
            #    is at `X86State.init`'s `rsp` and the peel's `a + 8 ≤ b` peels
            #    run out of writes before they run out of read.
            #
            # The second is the more interesting half, because it says the peel
            # was never the cheap route: it is a general argument about
            # `mem_write_bytes` that happens to be stated over the wrong read.
            # Both are now attempted, the affordable one first, and the peel is
            # dropped where it is known to be unaffordable.
            #
            # `hs_path` plus this step's OWN equation, because the goal is about
            # `s{k+1}` and not `s{k}` -- the same off-by-one the peel below
            # needed, and the reason `hs` is built above.
            for line in _concrete_read(hs_path + ("hs%d" % (k + 1),), rex):
                emit(line)
            if not crossed[0]:
                # The separation step, for a chain whose term is NOT closed --
                # a store through a register the program computed from its input
                # puts `n` in an address, and `native_decide` cannot evaluate a
                # term with a free variable in it. Its side condition is an
                # inequality over a `mem_write_bytes` chain, and it is stated
                # with `repeat rw` because `rw` peels ONE layer and the chain is
                # N deep -- see the B18 entry in
                # bugs/FORMAL_x86_64_end_to_end_proof.md for the measurement.
                #
                # Every step below is one that CANNOT fail: `simp` succeeds even
                # when it simplifies nothing, and the rest are `try`. So the
                # block always reaches `all_goals sorry`, which admits what is
                # left. `first | (...) | sorry` expresses the same thing but its
                # layout is fragile -- a `| sorry` one column out is read as an
                # alternative of the enclosing tactic and the file stops parsing.
                #
                # **The whole peel is inside one `try`, `have key` included,
                # because the attempt above it can CLOSE the goal** and a `have`
                # with nothing left to prove is `No goals to be solved`. That is
                # not a hypothetical: `const2`'s closing read is at
                # `X86State.init`'s stack and the evaluation closes it, so
                # `have key` was the next line and the file died with two
                # errors naming a lemma rather than the attempt that had
                # already succeeded.
                emit("  try")
                emit("    have key : ∀ (m : Nat → UInt8) (a : Nat)"
                     " (v : UInt64) (b : Nat),")
                emit("      a + 8 ≤ b → mem_read_bytes (mem_write_bytes m a v 8)"
                     " b 8")
                emit("        = mem_read_bytes m b 8 :=")
                emit("    fun m a v b h => mem_read_bytes_write_above m a v 8 8 b h")
                emit("    simp [%s, i0, X86State.init, x86_flags_sub," % hs)
                emit("      x86_flags_add, x86_set_reg, x86_get_reg, x86_rex_b,"
                     " x86_rex_r%s] <;>" % case_simp)
                emit("      try (repeat rw [key _ _ _ _ (by first | decide |"
                     " omega)]) <;>")
                emit("      try (simp only [mem_read_bytes, ite_true]) <;>")
                emit("      first | decide | omega")
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


#: A NAMED fact whose proof this emitter ADMITTED rather than closed:
#: `have <name> … := by`, followed — inside its body — by a `sorry`.
#: `have <name> … :=` — with or WITHOUT a `by`.  Both spellings open a proof, and
#: the one without matters: every step lemma is emitted as
#:     have hstep7 : x86_step s6 rc = some { … } :=
#:       x86_step_leave s6 rc … (by
#:         try (…)
#:         all_goals sorry) …
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
#: The GUARDED form — a tactic attempted immediately above it — is a different
#: fact entirely: the attempt runs first and the `sorry` is reached only if it
#: does not close the goal. Whether it fired is known only to Lean, and Lean
#: does not say, so counting a guarded `sorry` as a hole OVER-counts (measured:
#: 118 "admissions" on `wide_recv` where there are 5) and not counting it
#: UNDER-counts. They are reported as two numbers because they are two facts,
#: which is B21's whole subject.
_SORRY_ALONE = re.compile(r"^\s*(?:all_goals\s+)?sorry\s*$")
#: A `/- … -/` block comment, replaced by blank lines so the line numbers the
#: check reports still point at the source.
_BLOCK_COMMENT = re.compile(r"/-.*?-/", re.S)
#: **A `sorry` that shares its line with other syntax is inside an inline `by`,
#: and one alone on its line is a named fact's own admission.**  That is the
#: whole discriminator, and the emitter's two shapes are what makes it work:
#:
#:     have hstep7 : x86_step s6 rc = some { … } :=
#:       x86_step_leave s6 rc … (by
#:         try (…)
#:         all_goals sorry) (by …)          <- guarded: a SIDE CONDITION
#:
#:     have hrip : s16.rip = 0 := by
#:         try (simp only […])
#:         try (first | native_decide | decide)
#:         all_goals sorry                   <- admitted: this FACT's proof
#:
#: It used to be `(by try\b`, which matched the single-line side condition the
#: emitter used to write and nothing else — so a fact whose `try` chain closed
#: the goal and whose `all_goals sorry` then sat alone was counted as a hole
#: even when it was not one. That turned out to be the right answer for a wrong
#: reason, and it is kept: the count is only ever PRINTED when Lean says some
#: `sorry` in the file is load-bearing (`_run_lean`'s `fired`), and by then a
#: closed attempt is not in the printed set. Widening the regex to "an attempt
#: sits above it" instead — the other reading of the same two classes — was
#: measured and is worse: it makes every one of the 5171 guarded facts of the
#: 24-argument program a candidate and the report's answer to "which fact is the
#: hole" becomes `unattributed`.
#: …and one that SHARES its line with other syntax, which is a `sorry` inside
#: an inline `(by …)` — a step lemma's per-hypothesis argument.  The two shapes
#: the emitter writes are
#:
#:     all_goals sorry) (by          the first of three side conditions
#:     all_goals sorry)              the last one, where the `)` closes it
#:
#: so the discriminator is the LINE and nothing else: a fact's own admission is
#: `all_goals sorry` alone, a side condition's is never alone.  That is only
#: exact because those are the only two shapes emitted, which is what
#: `test_the_two_sorry_shapes_are_the_two_classes` pins.


def admitted_facts(text):
    """`[(name, line, kind)]` for every way this file's proof is short of closed.

    `kind` is `"admitted"` or `"guarded"`, and the two are counted separately by
    every caller because they answer different questions:

      `admitted`  a NAMED FACT's own last line: `have hpop{k} : … := by` and
                  then `all_goals sorry`. A hole in the file's scaffolding, and
                  the NAME is one a reader can go and look at.

      `guarded`   a SIDE CONDITION — a `sorry` inside an inline `(by …)`, which
                  is every step lemma's per-hypothesis argument. The tactic runs
                  first; the `sorry` is reached only if it does not close the
                  goal. So this is a fact about the EMISSION, not about the
                  proof: the fact may be fully proved and Lean says nothing
                  either way, because it reports "declaration 'terminates' uses
                  `sorry`" once per DECLARATION and
                  `formal/lean.py::_census_from_output` de-duplicates by name.
                  `bugs/FORMAL_x86_64_end_to_end_proof.md` reaches the same
                  conclusion about `augassign` from the other end, and this is a
                  statement about the CENSUS rather than the proof.

    **Neither count decides the verdict** — `_run_lean` asks Lean, which is the
    only thing that knows whether any of these `sorry`s is load-bearing. The
    counts are for NAMING a hole once Lean has said there is one, and **a name
    here is a CANDIDATE and not an identification**, which is why the report
    says `admitted candidate` and why this docstring's sentence needed the other
    half of its claim.

    The attribution is the nearest `have … := by` ABOVE the `sorry`, and that is
    exact for a fact's own admission and approximate for a side condition's: a
    side condition belongs to the step application that encloses it, and a step
    lemma is emitted WITHOUT a `by` (`have hstep7 : … := x86_step_…`), so `cur`
    is still the previous named fact when the side condition is read. Measured on
    `formal/examples/const2.mojo` — 16 steps, no `call`, so its closing read is
    the one at `X86State.init`'s stack — the census names `hrip`, and deleting the
    two `hrip` blocks' admissions and nothing else leaves the file checking
    with `returncode 0` and no errors while Lean still reports `declaration uses
    sorry`. **So the live hole is in one of the guarded side conditions and the
    name is the nearest enclosing fact, not the hole's owner.** Retiring that
    needs Lean's own positions — `set_option trace.Meta.Tactic.sorryAx`, which
    the tool this doc's next step names, DOES NOT EXIST in the pinned 4.32.2
    (`error: Unknown option`), and the real mechanism is a labeled sorry
    (`Lean.Meta.mkLabeledSorry`) read back with `Declaration.forEachSorryM`,
    which is a probe over the elaborated term and therefore a cost question
    rather than a flag.

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
            out.append((cur if cur is not None else ("_body", n), "guarded"))
    return [(nm, ln, kind) for (nm, ln), kind in out]


def admitted_phrase(n_admitted, names, n_guarded=None):
    """The one wording for "proved, and something in it is not proved".

    **The word `candidate` is load-bearing and is in this function because both
    report lines use it.** A name here is the nearest `have … := by` above a
    `sorry`, which is exact for a fact's own admission and is NOT the owner of a
    side condition's — a step lemma is emitted without a `by`, so a guard that
    fires inside one is charged to the fact before it. Measured on
    `formal/examples/const2.mojo`: the census named `hrip`, and deleting the two
    `hrip` blocks' admissions and nothing else left the file checking with
    `returncode 0` and no errors while Lean still reported `declaration uses
    sorry`. So the name is where the search STARTS. `admitted_facts` has the rest.

    Both theorems report through here so the two lines cannot drift into
    different claims about the same number, and a test can ask the wording a
    question without running Lean at all.
    """
    out = "%d admitted candidate (%s)" % (
        n_admitted, ", ".join(names) or "unattributed")
    if n_guarded is not None:
        out += ", %d guarded" % n_guarded
    return out


def _run_lean(text):
    """`(ok, n_admitted, fired, first_error)` for one generated Lean file.

    `n_admitted` is `admitted_facts`' count of the holes THIS emitter opened
    with nothing attempted above them, and `fired` is the one number only Lean
    has: whether any `sorry` in this file is LOAD-BEARING, which it reports as
    `declaration 'terminates' uses 'sorry'`, once per DECLARATION. `fired` is
    0 or 1 here and that is all the caller needs — it is the difference between
    "the guards all held" and "at least one did not", and no text census can
    see it.

    **The verdict is driven by `fired` and not by `n_admitted`, and that is the
    fix rather than a detail.** It was driven by `n_admitted`, which is a fact
    about what was EMITTED: so the 2815 guarded `sorry`s in the 8-argument
    program counted as zero holes whether or not their tactics closed their
    goals, and a single one of them falling through would have been reported as
    `PROVED`. The cross-check below would have caught it — by turning an admitted
    gap into a `FAIL`, which is B21's conflation from the other side, so it was
    a check that could only report the wrong answer. Asking Lean removes the
    question.

    The cross-check is still here and is still worth having, with the total
    (`n_admitted` + guarded) as its denominator: a `sorry` this emitter did not
    write at all would mean a library hole had leaked into a generated file, and
    a file with no `sorry` in it that Lean still calls `uses sorry` is exactly
    that.
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
            return (False, 0, False, p.exceeded)
        out = p.stdout + p.stderr
        if p.returncode != 0:
            # **A non-zero exit is not a PROOF, and it used to read as one.**
            # This function looked at `: error` lines and at nothing else, so a
            # `lean` that died without printing one came back `ok` — and the
            # caller reads `ok` as "the file elaborates". Measured on this
            # emitter's own 24-argument fixture: `(deterministic) timeout`-free,
            # zero `: error` lines, `sorry: []`, and `rc=-6` with
            #
            #     libc++abi: terminating due to uncaught exception of type
            #       lean::memory_exception: excessive memory consumption
            #       detected at 'interpreter'
            #
            # on stdout, from Lean's own allocator giving up at its default
            # `maxMemory`. Every number in the report was then a statement about
            # a file that was never checked, and `terminates: PROVED` was one of
            # them. This is the doc's own sentence about a check that is worse
            # than no check, arrived at from the other end: the guard was not
            # reporting a false proof, it was reporting no proof.
            #
            # The reason is the C++ runtime's own line where there is one,
            # because `lean::memory_exception` aborts rather than reports and
            # "exited -6" alone names the symptom rather than the cause.
            reason = next((l for l in out.splitlines()
                           if "memory_exception" in l or "libc++abi" in l), "")
            return (False, 0, False,
                    "lean exited %s: %s" % (p.returncode, reason
                                           or "no error message"))
        # Drop the temp path and the line:col, which would otherwise eat the
        # whole message under the `[:60]` slice below and print as a filename.
        errs = [_ERR.sub("", l) for l in out.splitlines() if ": error" in l]
        facts = admitted_facts(text)
        sorries = sum(1 for _n, _l, k in facts if k == "admitted")
        fired = any("declaration uses" in l for l in out.splitlines())
        if not errs and fired and not facts:
            errs.append(
                "Lean reports this declaration as using `sorry` and the "
                "generated file contains no `sorry` at all: a library hole has "
                "leaked into it, and reporting it as clean would be worse")
        return (not errs), sorries, fired, (errs[0] if errs else "")
    finally:
        os.unlink(tmp)


def _check(path, expected):
    """`(proved, n_admitted, fired, first_error)` for the value theorem."""
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
                good, val_sorries, val_fired, msg = _check(t, expected)
                val_holes = sorted({n for n, _l, k in admitted_facts(
                    emit(t, expected)) if k == "admitted"})
            except ValueError as exc:
                # No step lemma for some form: the theorem cannot even be
                # ATTEMPTED, which is missing coverage rather than a proof that
                # failed.  Reporting it as a failure is how "36 failing" happened
                # earlier.
                good, msg, uncovered = None, "", str(exc)
            if good and not val_fired:
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
                vs = "  value:     rax = %d, every input, %s" % (
                    expected, admitted_phrase(val_sorries, val_holes))
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
            ok, sorries, fired, err = _run_lean(text)
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
            if ok and not fired:
                term_ok += 1
                ts = "  terminates: PROVED"
            elif ok:
                # Lean's own answer, not the census's: a guarded `sorry` that
                # fell through is a hole and `fired` is what says so.
                #
                # **The names are CANDIDATES, and the word says so.** They are
                # the nearest `have … := by` above each `sorry`, which is exact
                # for a fact's own admission and is NOT the owner of a side
                # condition's: a step lemma is emitted without a `by`, so a
                # guard that fires inside one is charged to the previous fact.
                # Measured on `formal/examples/const2.mojo` (16 steps, no call):
                # the census names `hrip`, and deleting the two `hrip` blocks'
                # admissions and nothing else leaves the file checking with
                # `returncode 0` and no errors while Lean still reports
                # `declaration uses sorry` — so the live hole is one of the
                # guarded side conditions and `hrip` is where the search
                # starts. `admitted_facts` has the whole measurement; the
                # alternative is a probe over the elaborated term, and the
                # trace option this project would have reached for does not
                # exist in the pinned Lean.
                #
                # "unattributed" stays a real answer rather than a placeholder:
                # a `sorry` before any `have` has no name at all.
                term_gap += 1
                hole_total += sorries
                guard_total += guarded
                ts = "  terminates: proved, %s" % admitted_phrase(
                    sorries, holes, guarded)
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
    # name the emitter gave them. `admitted_facts` has why Lean cannot supply it
    # — and why the name is a candidate and not the hole's owner, which is the
    # one thing about these numbers a reader must not take as settled.
    print("               %d admitted fact(s) and %d guarded side condition(s) "
          "in the proved-with-a-sorry files, counted by name from the generated "
          "text; the name is the nearest enclosing fact, so a live `sorry` in a "
          "guarded side condition is charged to the step before it"
          % (hole_total, guard_total))
    print("               %d no finite tree (%d loop, %d uncovered form, "
          "%d returns into a caller, %d too large to prove)"
          % (notree + noform + nocall + nosize, notree, noform, nocall, nosize))
    print("  failing    : %d" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
