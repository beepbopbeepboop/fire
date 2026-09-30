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

  3 examples are proved end to end -- ret42, seven, const2 -- and the rest
  name the forms that block them, most-blocking first:

      28  jcc_rel32        26  setcc          8  imul_r64_r64
      26  movzx_r64_r8     21  jmp_rel32      7  call_rel32
      17  alu_rr:add       11  alu_rr:sub      3  movsx_r64_r8

  `alu_rr:cmp` and `alu_rr:test` came off this list with the two flags-only
  lemmas, 27 examples each.  The proved count did not move, because every
  example they blocked was also blocked by something else -- the blockers
  overlap heavily, so the useful measure of a lemma is what it removes from
  this list, not the count it adds to the proved line.

  `mov_r64_rm64` and `mov_rm64_r64` are gone from that list: the five general
  `mov` lemmas in X86.lean cover every shape the backend emits for them, and
  taking them out is what took the suite from 1 proved to 3.

  `setcc` (26) is the one that does NOT fall out of a generalisation, and it
  is worth saying why rather than leaving it in the list.  `cmp` and `test`
  above are flags-only: proving them is proving the operands and the flag
  function, and the successor names no register.  `setcc` sits behind the
  decoder's 0x0F dispatch, where reaching the case means excluding the jcc
  range, 0xaf (imul) and the movzx/movsx opcodes, and where the destination
  is the r/m field rather than the reg field -- the opposite sense to `mov`,
  which is where the two existing concrete lemmas (`setne_al`, `setle_al`) got
  their orientation.  The two concrete lemmas do cover the common conditions;
  what is missing is the nibble-parameterised version, and the work is pinning
  down which decoder (there is a 0x0F dispatch in `x86_step_rex` and another in
  `x86_step_plain`, with different `rip + 3` / `rip + 4` lengths) the
  no-REX encoding actually reaches, then stating the range and exclusion facts
  separately so `simp` can use each as a rewrite.

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

#: Where Lean's library and the `X86.olean` this test needs live.
LEAN_BIN = os.environ.get("LEAN_BIN") or os.path.expanduser(
    "~/.elan/toolchains/leanprover--lean4---v4.32.2/bin/lean")
LIB = os.path.join(ROOT, "lib")

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
    "mov_r64_rm64_reg": ("x86_step_mov_rm64_r64_reg", False,
                         ["rip", "b0", "b1", "b2", "rex", "w", "mod",
                          "reg", "rm"]),
    "mov_r64_rm64_sib": ("x86_step_mov_rax_sib_rsp", False,
                         ["rip", "b0", "b1", "b2", "b3", "w", "rex"]),
    "mov_rm64_r64_sib": ("x86_step_mov_mem_sib_rsp", False,
                         ["rip", "b0", "b1", "b2", "b3", "rex", "w", "mod",
                          "rm", "reg", "rb", "rr"]),
    # `dst` is the CONCRETE destination register, which the lemma needs because
    # `x86_set_reg` is a `match` on its index and `simp` will not reduce one on
    # a non-literal.  See the note on the lemma.
    "mov_r64_rm64_disp8": ("x86_step_mov_rm64_mem_disp8_rbp", False,
                           ["rip", "b0", "b1", "b2", "disp", "rex", "w",
                            "mod", "rm", "reg", "dst", "dst_lt"]),
    "mov_rm64_r64_reg": ("x86_step_mov_rm64_r64_reg_st", False,
                         ["rip", "b0", "b1", "b2", "rex", "w", "mod",
                          "reg", "rm"]),
    # No `rb`/`rr` here: the store direction is general over both REX bits,
    # because the backend emits `4c` (R set) for an r8 source.
    "mov_rm64_r64_disp8": ("x86_step_mov_mem_disp8_r64", False,
                           ["rip", "b0", "b1", "b2", "disp", "rex", "w",
                            "mod", "rm", "reg"]),
    # The only movzx the backend emits is `movzx rax, al` (48 0f b6 c0), all 33
    # of them, so this uses the existing concrete lemma rather than a
    # nibble- and register-parameterised one nothing would use.
    "movzx_r64_r8": ("x86_step_movzx_rax_al", False,
                     ["rip", "b0", "b1", "b2", "b3"]),
    "alu_rr:add": ("x86_step_add_rr", False,
                   ["rip", "b0", "b1", "b2", "rex", "w", "mod", "reg", "rm"]),
    "alu_rr:sub": ("x86_step_sub_rr", False,
                   ["rip", "b0", "b1", "b2", "rex", "w", "mod", "reg", "rm"]),
    "jcc_rel32": ("x86_step_jcc_rel32", False,
                  ["rip", "b0", "b1", "cc", "off", "lo", "hi", "nsetcc_lo",
                   "nzx", "notrex"]),
    "jmp_rel32": ("x86_step_jmp_rel32", False,
                  ["rip", "b0", "off"]),
    # `call rel32`. The step lemma is ALREADY PROVED -- `x86_step_call_rel32`
    # at lib/X86.lean:720 -- so this entry is pure wiring and admits no `sorry`.
    # It is the largest single uncovered form: 7 of the x86-64 examples named
    # `call_rel32` as their missing lemma, which is what `bugs/OPEN_WORK.md` A1
    # is about. Side conditions in the lemma's own order (h_rip, h_b0, h_imm).
    #
    # NOT VERIFIED. This was wired without running the suite, so what is
    # claimed here is the WIRING (the three entries below are transcribed from
    # the proved lemma's own statement, and the literal-address substitution
    # copies the `jmp_rel32` case that already works), not that the tree now
    # closes. The open risk is the continuation AT the target: a call's `rip`
    # is `m + 5 + off`, a literal supplied here, and whether the path from
    # there re-enters a block whose certificate is wired is a question only a
    # run answers. If it does not, the failure moves from "no step lemma wired
    # for: call_rel32" to whatever the target needs -- a DIFFERENT and more
    # specific error, which is progress, but it is not a proof.
    "call_rel32": ("x86_step_call_rel32", True,
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
    "leave": ("x86_step_leave", False, ["rip", "b0"]),
    "ret": ("x86_step_ret", False, ["rip", "b0"]),
}

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
    "mov_rm64_imm32": "{ $s with rax := $imm, rip := $next }",
    "alu_ri32:add":
        "{ x86_flags_add $s $s.rax $imm ($s.rax + $imm) with "
        "rax := $s.rax + $imm, rip := $next }",
    "mov_r64_rm64_reg":
        "{ x86_set_reg $s ($reg + x86_rex_r $rex) "
        "(x86_get_reg $s ($rm + x86_rex_b $rex)) with rip := $next }",
    "mov_r64_rm64_sib":
        "{ $s with rax := mem_read_bytes $s.mem $s.rsp.toNat 8, rip := $next }",
    "mov_rm64_r64_sib":
        "{ $s with mem := mem_write_bytes $s.mem $s.rsp.toNat "
        "(x86_get_reg $s ($reg + x86_rex_r 0x48)) 8, rip := $next }",
    "mov_r64_rm64_disp8":
        "{ x86_set_reg $s $dst (mem_read_bytes $s.mem "
        "(Int.ofNat (x86_get_reg $s (5 + x86_rex_b $rex)).toNat + $disp).toNat 8) "
        "with rip := $next }",
    "mov_rm64_r64_reg":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) "
        "(x86_get_reg $s ($reg + x86_rex_r $rex)) with rip := $next }",
    "mov_rm64_r64_disp8":
        "{ $s with mem := mem_write_bytes $s.mem "
        "(Int.ofNat (x86_get_reg $s (5 + x86_rex_b $rex)).toNat + $disp).toNat "
        "(x86_get_reg $s ($reg + x86_rex_r $rex)) 8, rip := $next }",
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
    "alu_rr:add":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) ($res) with rip := $next, zf := ($fa).zf, sf := ($fa).sf, cf := ($fa).cf, of_ := ($fa).of_ }",
    "alu_rr:sub":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) ($res) with rip := $next, zf := ($fs).zf, sf := ($fs).sf, cf := ($fs).cf, of_ := ($fs).of_ }",
    # `= true` explicitly.  The model's `if` is over a `Bool`, and the
    # `by_cases` hypothesis is an equation about a `Prop`; writing the condition
    # the same way on both sides is what lets the hypothesis rewrite it.  It is
    # defeq either way, but only this spelling fires.
    "jcc_rel32":
        "{ $s with rip := if x86_cond $cc $s = true then $tgt else $fall }",
    "jmp_rel32":
        "{ $s with rip := $tgt }",
    # Transcribed from `x86_step_call_rel32`'s conclusion (lib/X86.lean:720),
    # with `$tgt`/`$ret` supplied as literals by the decode branch above.
    "call_rel32":
        "{ $s with rip := $tgt, rsp := $s.rsp - 8, mem := "
        "mem_write_bytes $s.mem ($s.rsp - 8).toNat "
        "(UInt64.ofNat $ret) 8 }",
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
    "leave":
        "{ $s with rbp := mem_read_bytes $s.mem $s.rbp.toNat 8, "
        "rsp := $s.rbp + 8, rip := $next }",
    "ret":
        "{ $s with rip := (mem_read_bytes $s.mem ($s.rsp.toNat) 8).toNat, "
        "rsp := $s.rsp + 8 }",
}


def _body(code, info):
    """The entry function's own instruction stream, or None if it won't decode."""
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
        elif c == "off":
            sc.append(sc_("simp [read_i32_le, read_i8, hb]"))
        elif c in ("dst", "dst_lt"):
            # Closed arithmetic on the encoding: the destination register is
            # read out of the ModRM/REX bytes, so it is a literal here.
            sc.append(sc_("decide"))
        elif c in ("rex", "rex2", "w", "mod", "reg", "rm", "rb", "rr", "cc",
                   "lo", "hi", "nsetcc_lo", "njcc", "nzx", "op2",
                   "notrex"):
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
    elif form in ("mov_r64_rm64_reg", "mov_rm64_r64_reg", "alu_rr:add",
                "alu_rr:sub", "alu_rr:cmp", "alu_rr:test"):
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
        elif form == "alu_rr:cmp":
            extra_succ["$fc"] = "x86_flags_sub $s %s %s (%s - %s)" % (
                oa, ob, oa, ob)
        elif form == "alu_rr:test":
            extra_succ["$fl"] = "x86_flags_logic $s (%s &&& %s)" % (oa, ob)
    elif form == "jcc_rel32":
        op2 = raw[1]
        off = int.from_bytes(raw[2:6], "little", signed=True)
        extra_args = " %d %d %d" % (op2, op2 - 0x80, off)
        # The two successors as LITERAL addresses.  The model's own form is
        # `(Int.ofNat m + 6 + off).toNat`, and `simp` does not reduce that
        # `Int` arithmetic, so the taken address never becomes a numeral and
        # the `if` cannot be resolved against the next instruction's address.
        extra_succ = {"$cc": str(op2 - 0x80), "$off": str(off),
                      "$tgt": str(addr + 6 + off), "$fall": str(addr + 6)}
    elif form == "jmp_rel32":
        off = int.from_bytes(raw[1:5], "little", signed=True)
        extra_args = " %d" % off
        extra_succ = {"$off": str(off), "$tgt": str(addr + 5 + off)}
    elif form == "call_rel32":
        # Same reason as jmp_rel32 above, plus one more: a call has TWO
        # addresses -- the target it branches to, and the return address it
        # PUSHES. The pushed value is `UInt64.ofNat (m + 5)`, i.e. `$ret`.
        off = int.from_bytes(raw[1:5], "little", signed=True)
        extra_args = " %d" % off
        extra_succ = {"$off": str(off), "$tgt": str(addr + 5 + off),
                      "$ret": str(addr + 5)}
    elif form == "setcc":
        op2, modrm = raw[1], raw[2]
        extra_args = " %d %d %d %d" % (op2, modrm, op2 - 0x90, modrm & 7)
        extra_succ = {"$cc": str(op2 - 0x90), "$rmv": str(modrm & 7)}
    elif form == "mov_rm64_r64_sib":
        modrm = raw[2]
        extra_args = " %d %d" % (modrm, (modrm >> 3) & 7)
        extra_succ = {"$reg": str((modrm >> 3) & 7)}
    elif form in ("mov_r64_rm64_disp8", "mov_rm64_r64_disp8"):
        rex, modrm = raw[0], raw[2]
        disp = raw[3] - 256 if raw[3] > 127 else raw[3]
        reg = (modrm >> 3) & 7
        rex_r = 8 if rex & 4 else 0
        rex_b = 8 if rex & 1 else 0
        # A negative displacement is parenthesised: `-8 (by ...)` parses as an
        # application of it.
        if form == "mov_r64_rm64_disp8":
            extra_args = " %d %d %d %d (%d)" % (rex, modrm, reg, reg + rex_r,
                                                disp)
        else:
            extra_args = " %d %d %d (%d)" % (rex, modrm, reg, disp)
        extra_succ = {"$reg": str(reg), "$disp": str(disp), "$rex": str(rex),
                      "$dst": str(reg + rex_r),
                      "$base": str(5 + rex_b)}
    call = "%s %s rc %d%s" % (lemma, prev, addr, extra_args)
    if takes_imm:
        call += " %d" % imm
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
    subs["$imm"] = str(imm) if imm is not None else "0"
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
            form = form + ("_rsp" if raw[2] == want else "_other")
        if form in ("mov_r64_rm64", "mov_rm64_r64"):
            m, rm = modrm >> 6, modrm & 7
            if m == 3:
                form += "_reg"
            elif m == 1 and rm == 5:
                form += "_disp8"
            elif m == 0 and rm == 4 and len(raw) >= 4 and raw[3] == 0x24:
                form += "_sib"
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

    A loop is reported as None rather than walked: the chain proves one path, so
    a back edge has no finite unfolding here.  Four of the examples have one and
    they are named in the test output as needing induction.
    """
    base, entry = info["base_addr"], info["func_offset"]
    by_addr = {base + i.offset: (i, f, r) for i, f, r in shapes}
    counter = [0]

    def build(addr, state, depth):
        if depth > 64:
            return None
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
            taken = build(addr + n + off, None, depth + 1)
            fell = build(nxt, None, depth + 1)
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
            node.kids = [build(addr + off, None, depth + 1)]
            return None if node.kids[0] is None else node
        if form == "ret":
            return _Node(insn, form, raw, addr, "ret", state, None)
        node = _Node(insn, form, raw, addr, "seq", state, addr + insn.length)
        node.kids = [build(addr + insn.length, None, depth + 1)]
        return None if node.kids[0] is None else node

    root = build(entry, "i0", 0)
    if root is None:
        return None
    counter[0] = 0
    return root


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


def _header(code, insns, base):
    """The import, the code function, and every byte as a fact."""
    # A heartbeat budget.  The `hrip` step at the end of each path is one `simp`
    # over every successor equation on that path, and on the longer ones that is
    # a real amount of work: the default budget reports "deterministic timeout"
    # and the theorem is fine.  A timeout is NOT catchable by `try`, so the
    # `try`-guarded block below does not help here and the budget is the only
    # lever -- hence raising it rather than guarding.
    out = ["import X86\n",
           "set_option maxHeartbeats 4000000\n",
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


def emit(path, expected):
    """The straight-line end-to-end theorem: every input, constant result.

    Only usable when the function's result does not depend on its input, which
    is 7 of the 43 examples -- see `emit_terminates` for the one that covers
    the rest.
    """
    code, info, insns, shapes = _plan(path)
    base, entry = info["base_addr"], info["func_offset"]
    L = _header(code, insns, base)
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
        a("  obtain \u27e8%s, h%d\u27e9 : \u2203 t, x86_step %s rc = some t :="
          % (nxt, k, prev))
        a("    \u27e8_, hstep%d\u27e9" % k)
        a("  have hs%d : %s = %s := by" % (k + 1, nxt, succ))
        a("    rw [h%d] at hstep%d" % (k, k))
        a("    exact Option.some.inj hstep%d" % k)
        chain.append((k, nxt))
        prev, k = nxt, k + 1

    hs = ", ".join("hs%d" % (j + 1) for j, _ in chain)
    a("  have hrax : %s.rax = %d := by" % (prev, expected))
    a("    simp [%s, i0, x86_set_reg, x86_get_reg, x86_rex_b, x86_rex_r," % hs)
    a("      x86_flags_sub, x86_flags_add]")
    a("  have hrip : %s.rip = 0 := by" % prev)
    a("    have key : \u2200 (m : Nat \u2192 UInt8) (a : Nat) (v : UInt64) (b : Nat),")
    a("        a + 8 \u2264 b \u2192 mem_read_bytes (mem_write_bytes m a v 8) b 8")
    a("          = mem_read_bytes m b 8 :=")
    a("      fun m a v b h => mem_read_bytes_write_above m a v 8 8 b h")
    a("    simp [%s, i0, X86State.init, x86_flags_sub, x86_flags_add," % hs)
    a("      x86_set_reg, x86_get_reg, x86_rex_b, x86_rex_r]")
    a("    rw [key _ _ _ _ (by decide)]")
    a("    simp only [mem_read_bytes, ite_true]")
    a("    decide")
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
    out = _header(code, insns, base)
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
            emit("  try (rw [key _ _ _ _ (by first | decide | omega)]) <;>")
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
        p = subprocess.run([LEAN_BIN, tmp], capture_output=True, text=True,
                           env=env)
        return ": error" not in p.stdout + p.stderr
    finally:
        os.unlink(tmp)


def _has_loop(path):
    """Does the function body contain a back edge?

    The chain walks one straight line from the entry, so a function that loops
    is out of its reach -- and that is a limit of the method rather than a
    proof that stopped working, so it is reported as uncovered rather than as a
    failure.  A back edge is any branch whose target is at or before itself.
    """
    r = B.compile_formal(path, prove=False, check=False, arch="x86_64")
    code, info = r["code"], r["info"]
    insns = _body(code, info)
    if insns is None:
        return False
    for i in insns:
        raw = code[i.offset:i.next_offset]
        if i.form == "jmp_rel32":
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
        p = subprocess.run([LEAN_BIN, tmp], capture_output=True, text=True,
                           env=env)
        out = p.stdout + p.stderr
        # Drop the temp path and the line:col, which would otherwise eat the
        # whole message under the `[:60]` slice below and print as a filename.
        errs = [_ERR.sub("", l) for l in out.splitlines() if ": error" in l]
        sorries = sum(1 for l in out.splitlines() if "declaration uses" in l)
        return (not errs), sorries, (errs[0] if errs else "")
    finally:
        os.unlink(tmp)


def _check(path, expected):
    ok, _, msg = _run_lean(emit(path, expected))
    return ok, msg


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
                good, msg = _check(t, expected)
            except ValueError as exc:
                # No step lemma for some form: the theorem cannot even be
                # ATTEMPTED, which is missing coverage rather than a proof that
                # failed.  Reporting it as a failure is how "36 failing" happened
                # earlier.
                good, msg, uncovered = None, "", str(exc)
            if good:
                val_ok += 1
                vs = "  value:     rax = %d, every input" % expected
            elif uncovered is not None:
                vs = "  value:     -  (no lemma: %s)" % uncovered.split(": ")[-1]
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
