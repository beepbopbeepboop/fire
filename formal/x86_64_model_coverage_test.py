#!/usr/bin/env python3
"""Can the x86-64 model step every instruction the backend can emit?

`x86_step` returns `none` for anything it does not decode, and a run that
stops early is the failure mode that hides: the generated proof's result helper
maps a failed run to 0, so an unmodelled opcode does not fail anything — it
quietly produces a proof about a program that never ran. That is why every
generated run test carries a separate `_terminates_n` obligation.

This is the structural version of the same check. It takes the ENCODER's word
(`formal/x86_64.py`) rather than any program, enumerates what each `encode_*`
can produce, and asks the model to step every one of them. So the property
being tested is:

    every byte sequence this backend can emit is one `x86_step` can step

which no program-based test can state — a corpus only covers the forms the
corpus happens to use. Two things make it worth having:

  * a new `encode_*` is covered the moment it exists, with no example to
    write, so a form cannot be added to the backend and left unmodelled;
  * a REGRESSION in the model (a form that used to step and no longer does)
    fails here, immediately and by name, instead of turning some program's
    result quietly wrong.

Every sample is also run through `formal/x86_64_decode.py` first, so a failure
reported here is unambiguous: the model cannot step a form the backend really
does emit, rather than a sample that does not decode in the first place.

## What this does and does not prove

It proves COVERAGE, not correctness, and the difference is not academic: making
the model's `div` fall through to `idiv` leaves every sample still returning
`some` — it steps, to the wrong answer. So a form decoded wrongly is invisible
here, and that check is `formal/x86_64_model_test.py`, which runs the binaries
and compares. Between them: this one says "no form is unmodelled", that one says
"the forms the corpus uses are right". A form that is both unmodelled and unused
is caught only by this one; a form that is modelled but wrong is caught only by
the other.

## And the step lemmas, which coverage above cannot see

The samples answer "can the model step this?". They say nothing about whether
the per-instruction lemmas the proof chain is built from can be APPLIED, and
that is a separate failure with a separate history: `x86_step_setcc_r8` carried
`¬ ((0x80 : UInt8) ≤ op2)` when every `setcc` opcode byte is at least 0x90, so
its hypotheses were contradictory — which still compiles, still typechecks
against the model, and still proves its goal, and simply cannot be applied to
anything. 26 examples' worth of `setcc` sat there with a green suite, and
nothing short of writing the check down would have found it.

So `step_lemmas()` lists each lemma with an encoding the encoder really
produces, and this test makes Lean check that every one of the lemma's
hypotheses is satisfiable there, by `native_decide` on each. A failure prints
the hypothesis that did not close, by line, rather than a file name.

`movsx r64, r8` is checked at all three register shapes the corpus emits,
because a generalisation that covered only the shape it was written from would
pass a one-shape check.

Run: python3 formal/x86_64_model_coverage_test.py
Exit: 0 iff every emittable form steps and every listed lemma is applicable at
a real encoding.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import formal.x86_64 as X                                # noqa: E402
import formal.x86_64_decode as D                         # noqa: E402
import formal.lean as L                                  # noqa: E402
import formal.x86_64_endtoend_test as ET                 # noqa: E402

R = X.Reg
BASE = 0x1000
"""Where samples are placed. Any address works — the model addresses the code
function absolutely — but a round one makes a failure readable."""

#: Bounds for the two Lean runs this file makes (see `formal/lean.py` for the
#: policy and the measurements behind it). These are bigger than a proof check
#: because they are: 151 `native_decide` goals over every emittable encoding in
#: one file, and then a `decide` per hypothesis for every step lemma. Both used
#: to be a bare `subprocess.run(..., timeout=3600)` — a WALL bound only, on the
#: two runs in this tree most likely to spin, since a lemma whose hypotheses
#: are unsatisfiable reduces forever inside `decide`.
COVERAGE_WALL_S = 3600.0
COVERAGE_CPU_S = 3600.0


def _reg_pairs():
    """Register pairs worth covering: the low ones, the R8-R15 ones (REX.B/R),
    and a mixed pair. The model's register path differs between them, so a
    form that works for RAX can still be broken for R12."""
    return [(R.RAX, R.RCX), (R.R12, R.R14), (R.RAX, R.R15), (R.RSP, R.RBP)]


def samples():
    """[(form, label, bytes)] covering every `encode_*` in formal/x86_64.py."""
    out = []

    def add(form, label, enc):
        out.append((form, label, bytes(enc)))

    # push / pop, both REX and non-REX
    for reg in (R.RAX, R.RSP, R.RBP, R.R8, R.R12, R.R15):
        add("push_r64", "push %s" % reg.name, X.encode_push_r64(reg))
        add("pop_r64", "pop %s" % reg.name, X.encode_pop_r64(reg))
    add("ret", "ret", X.encode_ret())
    add("leave", "leave", X.encode_leave())
    add("nop", "nop", X.encode_nop())

    # mov, register and memory, 32- and 64-bit
    add("mov_rm64_imm32", "mov rax, imm32", X.encode_mov_r64_imm32(R.RAX, 0x41))
    add("mov_rm64_imm32", "mov r12, imm32", X.encode_mov_r64_imm32(R.R12, -5))
    add("mov_r64_imm64", "mov rax, imm64", X.encode_mov_r64_imm64(R.RAX, 1 << 40))
    add("mov_r64_imm64", "mov r9, imm64", X.encode_mov_r64_imm64(R.R9, 0xDEADBEEF))
    for dst, src in _reg_pairs():
        add("mov_rm64_r64", "mov %s, %s" % (dst.name, src.name),
            X.encode_mov_r64_r64(dst, src))
    for base, disp in ((R.RBX, 0), (R.RBP, 16), (R.RSP, 8), (R.R13, -0x1000),
                       (R.R12, 300)):
        add("mov_r64_rm64", "mov rax, [%s%+d]" % (base.name, disp),
            X.encode_mov_r64_rm64(R.RAX, base, disp))
        add("mov_rm64_r64", "mov [%s%+d], rax" % (base.name, disp),
            X.encode_mov_rm64_r64(base, disp, R.RAX))
    add("mov_rm32_r32", "mov eax, edx", X.encode_mov_r32_r32(R.RAX, R.RDX))
    add("mov_rm32_r32", "mov r8d, r9d", X.encode_mov_r32_r32(R.R8, R.R9))
    add("movsxd_r64_r32", "movsxd rax, edx",
        X.encode_movsx_r64_r32(R.RAX, R.RDX))
    add("movzx_r64_r8", "movzx rax, dl", X.encode_movzx_r64_r8(R.RAX, R.RDX))
    add("movsx_r64_r8", "movsx r10, r11b", X.encode_movsx_r64_r8(R.R10, R.R11))
    add("movzx_r64_r16", "movzx rax, dx", X.encode_movzx_r64_r16(R.RAX, R.RDX))
    add("movsx_r64_r16", "movsx rax, dx", X.encode_movsx_r64_r16(R.RAX, R.RDX))

    # ALU register/register
    for enc, name in ((X.encode_add_r64_r64, "add"), (X.encode_or_r64_r64, "or"),
                      (X.encode_and_r64_r64, "and"), (X.encode_sub_r64_r64, "sub"),
                      (X.encode_xor_r64_r64, "xor"), (X.encode_cmp_r64_r64, "cmp"),
                      (X.encode_test_r64_r64, "test")):
        for dst, src in ((R.R10, R.R11), (R.RAX, R.RBX)):
            add("alu_rr:%s" % name, "%s %s, %s" % (name, dst.name, src.name),
                enc(dst, src))
    add("alu_rr32:xor", "xor edx, edx", X.encode_xor_edx_edx())
    add("imul_r64_r64", "imul rax, rbx", X.encode_imul_r64_r64(R.RAX, R.RBX))
    add("imul_r64_r64", "imul r12, r15", X.encode_imul_r64_r64(R.R12, R.R15))

    # ALU register/immediate
    for enc, name, w in ((X.encode_add_r64_imm32, "add", 32),
                         (X.encode_or_r64_imm32, "or", 32),
                         (X.encode_and_r64_imm32, "and", 32),
                         (X.encode_sub_r64_imm32, "sub", 32),
                         (X.encode_xor_r64_imm32, "xor", 32),
                         (X.encode_cmp_r64_imm32, "cmp", 32)):
        for reg, imm in ((R.RAX, 1000), (R.R10, -7)):
            add("alu_ri%d:%s" % (w, name), "%s %s, %d" % (name, reg.name, imm),
                enc(reg, imm))
    for enc, name in ((X.encode_add_r64_imm8, "add"), (X.encode_and_r64_imm8, "and"),
                      (X.encode_sub_r64_imm8, "sub"), (X.encode_cmp_r64_imm8, "cmp")):
        for reg, imm in ((R.RAX, 7), (R.R9, -3)):
            add("alu_ri8:%s" % name, "%s %s, %d" % (name, reg.name, imm),
                enc(reg, imm))

    # unary / multiply / divide
    for enc, name in ((X.encode_neg_r64, "neg"), (X.encode_not_r64, "not"),
                      (X.encode_mul_r64, "mul"), (X.encode_imul_r64_1op, "imul1"),
                      (X.encode_div_r64, "div"), (X.encode_idiv_r64, "idiv")):
        for reg in (R.RAX, R.R11):
            add("group3:%s" % name, "%s %s" % (name, reg.name), enc(reg))
    add("cqo", "cqo", X.encode_cqo())

    # shifts
    for op, name in (("<<", "shl"), (">>", "shr"), (">>signed", "sar")):
        add("shift_imm8:%s" % name, "%s rax, 3" % name,
            X.encode_shift_r64_imm8(op, R.RAX, 3))
        add("shift_imm8:%s" % name, "%s r9, 40" % name,
            X.encode_shift_r64_imm8(op, R.R9, 40))
        add("shift_cl:%s" % name, "%s r9, cl" % name,
            X.encode_shift_r64_cl(op, R.R9))

    # lea
    add("lea_r64_rm64", "lea rax, [rbx+8]", X.encode_lea_r64_rm64(R.RAX, R.RBX, 8))
    add("lea_r64_rm64", "lea r10, [rsp+32]", X.encode_lea_r64_rm64(R.R10, R.RSP, 32))
    add("lea_r64_rm64", "lea r12, [r13-8]", X.encode_lea_r64_rm64(R.R12, R.R13, -8))
    add("lea_r64_rip", "lea rax, [rip+16]", X.encode_lea_r64_rip(R.RAX, 16))

    # setcc
    for enc, name in ((X.encode_sete, "sete"), (X.encode_setne, "setne"),
                      (X.encode_setl, "setl"), (X.encode_setle, "setle"),
                      (X.encode_setg, "setg"), (X.encode_setge, "setge"),
                      (X.encode_setb, "setb"), (X.encode_setbe, "setbe"),
                      (X.encode_seta, "seta"), (X.encode_setae, "setae")):
        for reg in (R.RAX, R.R11):
            add("setcc", "%s %s" % (name, reg.name), enc(reg))

    # branches and calls
    for cc in (0, 1, 2, 3, 4, 5, 6, 7, 10, 12, 14):
        add("jcc_rel8", "jcc rel8 cc=%d" % cc, X.encode_jcc_rel8(cc, 5))
        add("jcc_rel32", "jcc rel32 cc=%d" % cc, X.encode_jcc_rel32(cc, -70))
    add("jmp_rel8", "jmp rel8", X.encode_jmp_rel8(-3))
    add("jmp_rel32", "jmp rel32", X.encode_jmp_rel32(0x1234))
    add("call_rel32", "call rel32", X.encode_call_rel32(-0x2000))
    add("call_rm64", "call [rip+x]", X.encode_call_rm64(0x40))
    add("call_rm64", "call [rip-x]", X.encode_call_rm64(-0x40))
    add("jmp_rm64", "jmp [rip-x]", X.encode_jmp_rm64(-0x30))
    return out


class Lemma:
    """One step lemma, and the encoding the backend really emits for it.

    This is the second half of the coverage question, and it exists because
    "the file builds" is the wrong signal for a step lemma.  A lemma whose
    hypotheses are contradictory compiles, typechecks against the model, proves
    its goal, and can never be applied to anything — `x86_step_setcc_r8` carried
    `¬ ((0x80 : UInt8) ≤ op2)` when every `setcc` opcode byte is at least 0x90,
    and 26 examples' worth of `setcc` were in that state with a green suite.  So
    a lemma is covered only when a real encoding satisfies all of it, and the
    question worth asking about a new lemma is not "does it compile" but "can it
    be applied".

    What this does NOT check is the conclusion, and that is a decision rather
    than an omission.  Lean already checked it: `lib/X86.lean` compiling IS the
    conclusion being proved, so a `native_decide` of it here would be the same
    fact asked twice.  What compiling cannot tell you is applicability, which
    is exactly the half that was wrong.  (`Option X86State` has no `Decidable`
    instance anyway — `X86State.mem` is a `Nat → UInt8`, so the successor
    cannot be compared by evaluation at all, which is why the existing lemmas
    state whole successors and prove them by `simp`.)

    `hyp` is the lemma's own hypothesis list, concretised: each term is over
    `s` (the initial state) and `code` (the byte function), which the harness
    binds.
    """

    __slots__ = ("lemma", "label", "enc", "hyp")

    def __init__(self, lemma, label, enc, hyp):
        self.lemma, self.label, self.enc = lemma, label, bytes(enc)
        self.hyp = list(hyp)


def _rex_mod3_hyps(addr, rex, modrm, opcode, two_byte_op=False, reg=None,
                   digit=None, dst=None, mode=3):
    """The hypotheses a `REX.W <opcode> /r` mod=3 step lemma shares.

    Every form below is `REX`-prefixed, `REX.W`, and has a register operand, so
    the first eight of its hypotheses are the same eight bytes read four ways and
    the rest is whatever the form's own fields are.  Consolidating them here is
    what makes a form's entry below a transcription of its lemma's statement and
    not a fourth derivation of where a ModRM byte comes from.

    `reg` and `rm` are resolved by the caller and passed in, so this stays a
    transcription: two of the forms below carry a destination the caller read out
    of the REX, and recomputing it here would be a second source of truth for
    the field sense (`dst` is the DESTINATION, which is the `reg` field, and
    `rm` is the SOURCE -- the opposite of what the field names suggest).

    `digit` is for the shift forms, where the ModRM `reg` field names the
    OPERATION rather than a register; pass it instead of `reg` there.

    `two_byte_op` is the `0F` escape, and it is not a detail: with a REX byte at
    `m` the opcode moves to `m + 1` and the ModRM to `m + 2`, so an escape's
    `code (m + 2)` is the SECOND OPCODE rather than the ModRM.  That is the same
    off-by-one that made `imul` read its source register out of `0xaf &&& 7`
    (B19), and here it is the difference between a check that holds and one that
    does not.

    The `(x : UInt8).toNat` ascription is not decoration, twice over.  Lean
    reads `192.toNat` as a malformed decimal — a PARSE error, and in a check
    file a parse error is a check that did not run — and `(192).toNat` parses but
    elaborates `192` as a `Nat`, which has no `toNat` field, so the hypothesis
    is an elaboration error instead.  The ascription is what makes it the same
    expression the lemma states about a `UInt8` ModRM byte.
    """
    b = "(%d : UInt8).toNat" % modrm
    hyp = ["s.rip = %d" % addr, "code %d = %d" % (addr, rex)]
    if two_byte_op:
        hyp += ["code %d = %d" % (addr + 1, 0x0f),
                "code %d = %d" % (addr + 2, opcode),
                "code %d = %d" % (addr + 3, modrm)]
    else:
        hyp += ["code %d = %d" % (addr + 1, opcode),
                "code %d = %d" % (addr + 2, modrm)]
    hyp += [
        "x86_is_rex %d = true" % rex,
        "x86_rex_w %d = true" % rex,
        "%s >>> 6 = %d" % (b, mode),
    ]
    if digit is not None:
        hyp.append("(%s >>> 3) &&& 7 = %d" % (b, digit))
    if reg is not None:
        hyp.append("(%s >>> 3) &&& 7 = %d" % (b, reg))
    hyp.append("%s &&& 7 = %d" % (b, modrm & 7))
    if dst is not None:
        hyp.append("%d + x86_rex_r %d = %d" % (reg, rex, dst))
    return hyp


def _rex_mem_hyps(addr, rex, modrm, opcode, mode, rm_ne, dst=None, sib=False):
    """Hypotheses for a `REX.W <opcode> /r` MEMORY form, concretised.

    The memory forms carry what the register ones do not: the ModRM `mod` is the
    addressing mode rather than always 3, and the exclusions on the rm field are
    hypotheses -- `rm ≠ 4` for "no SIB byte follows", and `rm ≠ 5` as well at
    mod=0, where rm=5 is RIP-relative rather than `[rbp]`.  Leaving either out is
    a statement about a different instruction: without the first the
    displacement is read from the wrong byte, without the second a
    position-independent load is claimed to be `mov [rbp]`.

    `mode` is a PARAMETER rather than something read back out of the encoding,
    because the check's whole job is to notice when a row's lemma and a row's
    encoding disagree -- which is exactly what `lea r11, [rbx+64]` did: 64 fits
    in a signed byte, so the encoder emitted a disp8 and the disp32 lemma's
    `mod = 2` hypothesis did not hold.

    `dst` is the CONCRETE destination register for the forms whose successor is
    a register WRITE -- every `mov r64, [...]` and every `lea` -- and it is
    emitted together with the `dst < 16` that `x86_set_reg` is a `match` on, so
    both halves of what the load's hypothesis list actually says are checked.
    Passing it is what makes this a transcription of the LEMMA's statement: both
    hypotheses were absent here before, so a load whose destination index was
    computed wrongly would have satisfied every hypothesis in this list and
    proved nothing about where the value lands.

    `sib` adds the two facts a SIB operand carries and a `[rbp + disp]` one does
    not: the SIB byte itself, which sits BETWEEN the ModRM and the displacement
    (so the displacement is at `m + 4` and not `m + 3`), and `REX.B = 0`, which is
    what makes the SIB's base field `4` mean RSP rather than R12.  Neither is
    derivable from the other three byte facts, so a row for a SIB form without
    them would check the wrong displacement offset.
    """
    hyps = _rex_mod3_hyps(addr, rex, modrm, opcode,
                          reg=(modrm >> 3) & 7, mode=mode, dst=dst)
    if sib:
        hyps.append("code %d = %d" % (addr + 3, 0x24))
    if dst is not None:
        hyps.append("%d < 16" % dst)
    if sib:
        hyps.append("x86_rex_b %d = 0" % rex)
    for r in rm_ne:
        hyps.append("%d ≠ %d" % (modrm & 7, r))
    return hyps


def step_lemmas():
    """Every step lemma this test holds to the applicability check above."""
    R = X.Reg
    out = []
    # `movsx r64, r8`.  All THREE register shapes the corpus emits, because that
    # is the whole argument for the lemma being general rather than a second
    # concrete `movsx rax, al`: a generalisation that covered only the shape it
    # was written from would pass a one-shape check.
    for dst, src in ((R.RAX, R.RAX), (R.RBX, R.RBX), (R.R10, R.R11)):
        enc = X.encode_movsx_r64_r8(dst, src)
        rex, modrm = enc[0], enc[3]
        reg, rm = (modrm >> 3) & 7, modrm & 7
        d = reg + (8 if rex & 4 else 0)
        out.append(Lemma(
            "x86_step_movsx_r64_r8",
            "movsx %s, %s" % (dst.name, src.name),
            enc,
            _rex_mod3_hyps(BASE + 16 * len(out), rex, modrm, 0xbe,
                           two_byte_op=True, reg=reg, dst=d)))
    # The three logic ALU forms, at register pairs that exercise BOTH REX
    # extension bits and neither.  The corpus only ever emits `4c 2?/0?/3? d8`
    # -- `and rax, rbx` and nothing else -- so a check written from the corpus
    # would pass a lemma that is wrong for R12/R15, which is the trap B7 is
    # about and the reason these are stated generally in the first place.
    for name, enc_fn, opcode in (("and", X.encode_and_r64_r64, 0x21),
                                 ("or", X.encode_or_r64_r64, 0x09),
                                 ("xor", X.encode_xor_r64_r64, 0x31)):
        for dst, src in _reg_pairs():
            enc = enc_fn(dst, src)
            out.append(Lemma(
                "x86_step_%s_rr" % name,
                "%s %s, %s" % (name, dst.name, src.name),
                enc,
                _rex_mod3_hyps(BASE + 16 * len(out), enc[0], enc[2], opcode,
                               reg=(enc[2] >> 3) & 7)))
    # The immediate shifts.  `sar` is digit 7 and is the model's arithmetic-shift
    # FALLTHROUGH rather than a third named arm, so it is checked at a count
    # past 63 as well as inside it: the clamp to 64 is what makes `sar x, 200`
    # mean `sar x, 64` and a lemma that needed a `n < 64` hypothesis would fail
    # there, which is the one thing this check can catch that compiling cannot.
    for name, op, digit in (("shl", "<<", 4), ("shr", ">>", 5),
                            ("sar", ">>signed", 7)):
        for reg, n in ((R.RAX, 3), (R.R11, 200)):
            enc = X.encode_shift_r64_imm8(op, reg, n)
            out.append(Lemma(
                "x86_step_%s_imm8" % name,
                "%s %s, %d" % (name, reg.name, n),
                enc,
                _rex_mod3_hyps(BASE + 16 * len(out), enc[0], enc[2], 0xc1,
                               digit=digit)))
    # The digit-immediate ALU forms, at both widths and at a negative immediate
    # as well as a positive one.  `83`'s sign extension from ONE byte is the
    # thing worth pinning: a lemma stated over the decoded Python integer rather
    # than over `UInt8.toInt` would disagree with the model for every negative
    # `cmp`, and 0xff decoding as -1 is exactly the case.
    for name, enc_fn, opcode, digit, args in (
            ("add", X.encode_add_r64_imm32, 0x81, 0, ((R.RAX, 1000), (R.R9, -7))),
            ("and", X.encode_and_r64_imm32, 0x81, 4, ((R.RBX, -1), (R.R11, 255))),
            ("cmp", X.encode_cmp_r64_imm8, 0x83, 7, ((R.RAX, 0), (R.R11, -3)))):
        for reg, imm in args:
            enc = enc_fn(reg, imm)
            out.append(Lemma(
                "x86_step_%s_ri%d" % (name, 8 if opcode == 0x83 else 32),
                "%s %s, %d" % (name, reg.name, imm),
                enc,
                _rex_mod3_hyps(BASE + 16 * len(out), enc[0], enc[2], opcode,
                               digit=digit)))
    # The memory-operand `mov`/`lea` shapes, at every mode the corpus uses and at
    # both a negative and a positive displacement.  `wide_recv`'s frame lives at
    # `rbp - 0x410`, so a lemma that read the disp32 UNSIGNED would put every
    # frame store about 4 GB away -- and satisfy every hypothesis this check
    # makes, because the exclusion it tests is about the rm field and not about
    # the sign of the displacement.  The mode is read back out of the encoding
    # rather than written down here, so a row cannot disagree with the encoder.
    # `cqo`: no operand and no ModRM, so it does not go through the shared
    # hypothesis helper at all.  `encode_cqo` is the only producer and there is
    # nothing to vary but the REX byte, which is fixed at 0x48.
    cqo = X.encode_cqo()
    out.append(Lemma(
        "x86_step_cqo", "cqo", cqo,
        ["s.rip = %d" % (BASE + 16 * len(out)),
         "code %d = %d" % (BASE + 16 * len(out), cqo[0]),
         "code %d = %d" % (BASE + 16 * len(out) + 1, cqo[1]),
         "x86_is_rex %d = true" % cqo[0],
         "x86_rex_w %d = true" % cqo[0]]))
    # `movq xmm, r64`: the GPR-to-SSE move, and the one emittable form whose
    # FIRST byte is not the REX.  Two rows, not one, and the reason is the two
    # properties that have to be true at once and cannot both be checked at one
    # encoding: the XMM number comes from the ModRM `reg` field with NO REX.R, and
    # the source GPR comes from `rm` WITH REX.B.  At `xmm0`/`rax` both are 0, so
    # a row there would be satisfied by a lemma that dropped either extension
    # and put REX.R on the XMM index.  `xmm3`/`r12` is the encoding where a
    # dropped REX.R names XMM11 and a dropped REX.B names RSP.
    for xmm, gpr in ((0, X.Reg.RAX), (3, X.Reg.R12)):
        enc = X.encode_movq_xmm_rm64(xmm, gpr)
        m = BASE + 16 * len(out)
        out.append(Lemma(
            "x86_step_movq_xmm_rm64", "movq xmm, %s" % gpr.name, enc,
            ["s.rip = %d" % m,
             "code %d = %d" % (m, enc[0]),
             "code %d = %d" % (m + 1, enc[1]),
             "code %d = %d" % (m + 2, enc[2]),
             "code %d = %d" % (m + 3, enc[3]),
             "code %d = %d" % (m + 4, enc[4]),
             "x86_is_rex %d = true" % enc[1],
             "x86_rex_w %d = true" % enc[1],
             "x86_is_rex %d = false" % enc[0],
             # `(%d : UInt8).toNat` and not `%d.toNat`, and the reason is
             # `_rex_mod3_hyps`'s own docstring: Lean reads a bare `192.toNat` as
             # a malformed decimal and `(192).toNat` elaborates 192 as a `Nat`,
             # which has no `toNat` field.  Written the other way this row was
             # an elaboration ERROR, and the applicability report attributed it
             # to a hypothesis that does hold -- which is how a check for
             # vacuous lemmas ends up reporting one that never ran.
             "(%d : UInt8).toNat >>> 6 = 3" % enc[4]]))
    for lemma, label, enc, dst, sib in _memory_samples():
        # `rm ≠ 4` is the "no SIB byte follows" exclusion, so a SIB row is the one
        # shape where it must NOT be asserted -- rm=4 is what SELECTS the SIB.
        # Asserting it anyway gives `4 ≠ 4`, and this check is what said so:
        # "hypothesis 12 `4 ≠ 4` does not hold at 48 89 44 24 08 -- the lemma is
        # vacuous there", which named the row and the bytes.  A vacuous
        # hypothesis is worse than a missing one: the lemma would still prove.
        out.append(Lemma(
            lemma, label, enc,
            _rex_mem_hyps(BASE + 16 * len(out), enc[0], enc[2], enc[1],
                          (enc[2] >> 6) & 3, () if sib else (4,), dst, sib)))
    return out


def _memory_samples():
    """`(lemma, label, encoding, dst, sib)` for the memory-operand shapes, both
    directions.

    Read back out of the encoder rather than spelled as byte strings, because a
    hand-written encoding here is a third place for a typo to live and the only
    thing the check needs from it is that it is a real one.

    `dst` is the concrete destination for the forms whose successor writes a
    register, and `None` for the stores, which have none; `sib` marks the rows
    whose encoding carries a SIB byte.  Both are read off the row rather than
    derived, because they are transcriptions of what the LEMMA says and a
    derived one is the fourth derivation this file exists to avoid.
    """
    R = X.Reg

    def load(lemma, label, enc, sib=False):
        """A memory form whose successor WRITES a register, so its lemma takes the
        concrete destination -- read out of the encoding here, which is where the
        check is supposed to get its facts from.  `sib` marks the rows whose
        encoding carries a SIB byte."""
        return (lemma, label, enc, ((enc[2] >> 3) & 7) + (8 if enc[0] & 4 else 0),
                sib)

    def store(lemma, label, enc):
        """A memory form whose successor writes MEMORY, so its lemma has no `dst`
        at all and passing one would be a hypothesis the lemma does not have."""
        return (lemma, label, enc, None, False)

    def sib_store(lemma, label, enc):
        """A store through a SIB operand: `Reg.RSP` as the base is what makes the
        encoder emit one, so these rows are read back out of that path rather
        than spelled."""
        return (lemma, label, enc, None, True)

    def sib_load(lemma, label, enc):
        """A LOAD through a SIB operand — `load` with the SIB byte marked, so the
        check adds the two facts a SIB encoding carries and a `[rbp+disp]` one
        does not: the SIB byte itself at `m + 3`, and `REX.B = 0`."""
        return load(lemma, label, enc, sib=True)

    return [
        # The two SIB forms with NO displacement, load and store.
        #
        # These are the pair this list carried NO ROW for, and that omission is
        # the whole reason a statement pinned to `0x48`/`rax` could sit here
        # unchallenged: `x86_step_mov_rax_sib_rsp` said "every SIB operand the
        # backend emits has this shape", which is a fact about the SIB BYTE and
        # not about the instruction — `_pop_slot(Reg.R11)` emits `4c 8b 1c 24`.
        # Applied by form name, that was proved as `48 8b 04 24`, its byte
        # hypotheses were false, and the generator's side-condition guard
        # admitted them instead of reporting them: `augassign` read
        # `terminates: proved, 1 sorry` about a chain with a step that is not
        # the one the machine runs.
        #
        # So both rows come in pairs, REX.R clear and set, because `rex` bit 4 is
        # exactly what moves the named register out of r0-r7 and into r8-r15 and
        # the generalisation is about `reg + x86_rex_r rex` covering both.  A
        # third load row at r15 is the top of the register file, which is where
        # an off-by-one in the REX extension would show.
        sib_load("x86_step_mov_rm64_sib_rsp", "mov rax, [rsp]",
                 X.encode_mov_r64_rm64(R.RAX, R.RSP, 0)),
        sib_load("x86_step_mov_rm64_sib_rsp", "mov r11, [rsp]",
                 X.encode_mov_r64_rm64(R.R11, R.RSP, 0)),
        sib_load("x86_step_mov_rm64_sib_rsp", "mov r15, [rsp]",
                 X.encode_mov_r64_rm64(R.R15, R.RSP, 0)),
        sib_store("x86_step_mov_mem_sib_rsp", "mov [rsp], rax",
                  X.encode_mov_rm64_r64(R.RSP, 0, R.RAX)),
        sib_store("x86_step_mov_mem_sib_rsp", "mov [rsp], r12",
                  X.encode_mov_rm64_r64(R.RSP, 0, R.R12)),
        load("x86_step_mov_rm64_mem_disp8", "mov rax, [rbp+8]",
             X.encode_mov_r64_rm64(R.RAX, R.RBP, 8)),
        load("x86_step_mov_rm64_mem_disp8", "mov r12, [rbp-8]",
             X.encode_mov_r64_rm64(R.R12, R.RBP, -8)),
        load("x86_step_mov_rm64_mem_nodisp", "mov r8, [rbx]",
             X.encode_mov_r64_rm64(R.R8, R.RBX, 0)),
        store("x86_step_mov_mem_disp8", "mov [rbp+8], rax",
              X.encode_mov_rm64_r64(R.RBP, 8, R.RAX)),
        store("x86_step_mov_mem_disp8", "mov [rbx+8], r12",
              X.encode_mov_rm64_r64(R.RBX, 8, R.R12)),
        store("x86_step_mov_mem_nodisp", "mov [rdx], r11",
              X.encode_mov_rm64_r64(R.RDX, 0, R.R11)),
        store("x86_step_mov_mem_disp32", "mov [rbp-0x410], rax",
              X.encode_mov_rm64_r64(R.RBP, -0x410, R.RAX)),
        store("x86_step_mov_mem_disp32", "mov [rbx+4096], r9",
              X.encode_mov_rm64_r64(R.RBX, 4096, R.R9)),
        load("x86_step_lea_rm64_disp32", "lea rax, [rbp-0x410]",
             X.encode_lea_r64_rm64(R.RAX, R.RBP, -0x410)),
        # 64 would encode as a disp8 -- `_rm_disp` picks the narrowest form --
        # and this row is here to pin the disp32 one.
        load("x86_step_lea_rm64_disp32", "lea r11, [rbx+4096]",
             X.encode_lea_r64_rm64(R.R11, R.RBX, 4096)),
        # The disp32 LOAD, which is what a stack argument past the twentieth
        # encodes to: `_load_home_from_stack` reads `mov r11, [rbp + 16 + 8k]`
        # and `16 + 8k` crosses 127 at k = 14, so argument index 20 is the first
        # one with a four-byte displacement.  128 is therefore the SMALLEST
        # displacement that reaches this encoding, and a row at 120 would be a
        # disp8 row wearing this lemma's name -- the `lea r11, [rbx+64]` trap in
        # the one place it has not happened yet.
        load("x86_step_mov_rm64_mem_disp32", "mov r11, [rbp+128]",
             X.encode_mov_r64_rm64(R.R11, R.RBP, 128)),
        # And the negative side, because the displacement is SIGNED: a lemma
        # that read its four bytes unsigned would put a `mov r11, [rbp-0x410]`
        # about 4 GB away, and every other hypothesis in this list would still
        # hold, because the sign of the displacement is not one of them.
        load("x86_step_mov_rm64_mem_disp32", "mov r11, [rbp-0x410]",
             X.encode_mov_r64_rm64(R.R11, R.RBP, -0x410)),
        # The two SIB stores a call site emits for every argument past the
        # register file.  `[rsp + disp]` has NO non-SIB encoding (at mod=0 rm=5 is
        # RIP-relative), so these are not a variant of the `mov_rm64_r64_disp8`
        # rows above but a different instruction, and the whole
        # stack-argument convention on the CALLER side is made of them.  128 is
        # the first displacement that needs four bytes, for the same reason the
        # load above is at 128: `_rm_disp` picks the narrowest form, and a row at
        # 120 would be a disp8 row wearing the disp32 lemma's name.
        sib_store("x86_step_mov_mem_sib_disp8", "mov [rsp+8], rax",
                  X.encode_mov_rm64_r64(R.RSP, 8, R.RAX)),
        sib_store("x86_step_mov_mem_sib_disp32", "mov [rsp+128], rax",
                  X.encode_mov_rm64_r64(R.RSP, 128, R.RAX)),
        # And with a high source register, which is the `4c` prefix the two
        # lemmas are general over -- `x86_step_mov_mem_sib_rsp` pins `0x48`, and a
        # row at `0x48` only would leave every argument the compiler keeps in
        # r8..r15 unchecked.
        sib_store("x86_step_mov_mem_sib_disp8", "mov [rsp+8], r12",
                  X.encode_mov_rm64_r64(R.RSP, 8, R.R12)),
    ]


#: The forms whose SUCCESSOR this file also checks against the model, with the
#: encoder to read the bytes from.  Distinct from `step_lemmas()` above, which
#: asks whether a lemma's HYPOTHESES can hold; this asks whether the successor
#: the end-to-end emitter writes is the successor the model computes.
#:
#: The two answer different questions and both have been needed.  A `cqo` whose
#: `_SUCCS` row said `x86_sign_extend32` while the model's arm computes
#: `x86_cqo` left every hypothesis satisfiable — so the row above was green —
#: and the end-to-end proof of that step was a proof of a different instruction.
#: That is the whole argument for having this: the applicability check cannot
#: see a successor at all, and a successor is a second copy of the model that
#: has to be kept in step with it.
#:
#: Read out of the ENCODER, so the bytes are the ones the backend emits, and the
#: successor out of `_resolve`, so the check is against what the generator
#: actually writes rather than against a hand-written copy of it.
#: `(form, encoding, probe)` — the probe is `X86State -> (Nat x UInt64)`, the
#: `rip` and the ONE field the instruction writes.  It is a fact about the
#: instruction, not a copy of the successor, so the check below stays
#: non-circular: it compares the model's step against the emitter's successor on
#: the fields the instruction is ABOUT.
#:
#: `RDI` and not `R12` for the `movq` source, and that is the whole reason the
#: row has teeth.  `X86State.init 10 _` sets `rdi := 10` and every other general
#: register to 0, so an encoding whose source is RDI carries a NON-ZERO value
#: into the XMM slot -- and swapping the two halves of the ModRM, which is the
#: one mistake this instruction invites, then reads `rbx` (0) instead and the two
#: successors differ.  At `x12`/`r12`, which is the pair the applicability rows
#: use, both halves are 0 and the swap is invisible.
SUCCESSOR_FORMS = (
    ("cqo", X.encode_cqo(), "fun t => (t.rip, t.rdx)"),
    ("movq_xmm_rm64", X.encode_movq_xmm_rm64(3, X.Reg.RDI),
     "fun t => (t.rip, t.xmm3)"),
)


def successor_lean_source(forms):
    """`(text, checks)` — one `native_decide` per form's successor claim.

    The claim is `(x86_step s code).map PROBE = (some EMITTER_SUCC).map PROBE`
    rather than the two records compared whole, and the reason is `Decidable`:
    a successor carries `mem : Nat -> UInt8`, so record EQUALITY on two of them
    is not decidable and `native_decide` reports "failed to synthesize Decidable"
    -- which is an error, so it is caught, but it says nothing about the
    successor.  Mapping both sides through a probe puts them in
    `Option (Nat x UInt64)`, which is decidable and computable.
    """
    out = ["import X86", ""]
    checks = []
    for i, (form, enc, probe) in enumerate(forms):
        m = BASE + 16 * i
        items = ", ".join("0x%02x" % b for b in enc)
        out.append("def scode_%d (code : Nat) : UInt8 :=" % i)
        out.append("  if code < %d then 0 else ([%s].getD (code - %d) 0)"
                   % (m, items, m))
        out.append("def sst_%d : X86State := X86State.init 10 %d" % (i, m))
    for i, (form, enc, probe) in enumerate(forms):
        succ = ET._resolve(form, enc, BASE + 16 * i, "s", 0, length=len(enc))[1]
        claim = ("(let s := sst_%d; let code := scode_%d; "
                 "(x86_step s code).map (%s) = (some %s).map (%s))"
                 % (i, i, probe, succ, probe))
        first = len(out) + 1
        checks.append((first, first + 2, form,
                       "the emitter's successor for %s disagrees with the "
                       "model's step at %s on rip or on the field this "
                       "instruction writes — the end-to-end proof of this step "
                       "is about a different instruction than the one the model "
                       "runs" % (form, enc.hex(" "))))
        out.append("/-- %s at %s: the model's step and the emitter's successor "
                   "agree on rip and on the field it writes -/"
                   % (form, enc.hex(" ")))
        out.append("example : %s := by" % claim)
        out.append("  native_decide")
    return "\n".join(out) + "\n", checks


def lemma_lean_source(lems):
    """`(text, checks)` — the applicability file, and where each check landed.

    `checks` is `(first_line, last_line, label, why)` per `example`, and the
    caller attributes a Lean diagnostic by LINE rather than by matching the
    emitted text back.  Two things went wrong the other way and both are worth
    writing down:

      * an `example (s := ls_0) : …` binder does NOT bind.  `s` stays a free
        variable and `native_decide` rejects the goal ("Expected type must not
        contain free variables"), so every check errored — and a version that
        matched the emitted `example` line back found none of them, because an
        error means Lean printed the line instead.  A check that cannot fail is
        worse than no check: it is green.  `let` inside the type works, and is
        what is emitted.
      * the error lands on the `native_decide` line, one below the statement,
        and on the statement line when the failure is elaboration.  So each
        check records a RANGE and the caller attributes by range.

    Every statement is therefore self-contained:
    `example : (let s := ls_0; let code := lcode_0; <term>) := by native_decide`.
    """
    out = ["import X86", ""]
    checks = []
    for i, lem in enumerate(lems):
        m = BASE + i * 16
        items = ", ".join("0x%02x" % b for b in lem.enc)
        out.append("def lcode_%d (code : Nat) : UInt8 :=" % i)
        out.append("  if code < %d then 0 else ([%s].getD (code - %d) 0)"
                   % (m, items, m))
        out.append("def ls_%d : X86State := X86State.init 10 %d" % (i, m))
    for i, lem in enumerate(lems):
        bind = "example : (let s := ls_%d; let code := lcode_%d; %%s) := by" % (i, i)
        for j, h in enumerate(lem.hyp):
            out.append("/-- %s, hypothesis %d: `%s` -/" % (lem.label, j + 1, h))
            first = len(out) + 1
            checks.append((first, first + 1, lem.label,
                           "hypothesis %d `%s` does not hold at %s — the lemma "
                           "is vacuous there"
                           % (j + 1, h, lem.enc.hex(" "))))
            out.append(bind % h)
            out.append("  native_decide")
    return "\n".join(out) + "\n", checks


_LEAN_LOC = re.compile(r"^(\S+):(\d+):\d+: error: ", re.M)


def lemma_check_failures(out, checks, filename):
    """The `checks` ranges Lean reported an error in, in file order.

    Matched on the BASENAME, and that is not tidiness — it is the difference
    between a check and a green. `run_lean` is handed an ABSOLUTE path (the
    scratch directory is private and per-run), and Lean prints the path it was
    given, so the diagnostic names `/var/folders/…/StepLemmas.lean:412` while
    the caller holds `"StepLemmas.lean"`. Comparing the two strings never
    matched, so no diagnostic was ever attributed to a check and the report read
    `every hypothesis satisfiable` whatever Lean said.

    Measured, on a planted falsehood and on a planted wrong successor: both
    printed exactly that line and exited 0. It is the failure mode this file's
    own docstring names — "a check that cannot fail is worse than no check: it is
    green" — and it is the one place in this project where the check that exists
    to catch a vacuous lemma was itself vacuous.

    A whole-path match is kept as a fallback so a caller that does pass the
    absolute path is not made worse by the fix.
    """
    at = set()
    for m in _LEAN_LOC.finditer(out):
        if m.group(1) == filename or os.path.basename(m.group(1)) == filename:
            at.add(int(m.group(2)))
    return [(label, why, sorted(n for n in at if lo <= n <= hi))
            for lo, hi, label, why in checks if any(lo <= n <= hi for n in at)]


def lean_source(samps):
    out = ["import X86", "",
           "/-- Each sample sits at its own address so a failure names the form. -/",
           "def at (base : Nat) (i : Nat) : UInt8 :=",
           "  match base + i with",
           "  | _ => 0"]
    for i, (form, label, enc) in enumerate(samps):
        items = ", ".join("0x%02x" % b for b in enc)
        out.append("def code_%d (a : Nat) : UInt8 :=" % i)
        out.append("  if a < %d then 0 else ([%s].getD (a - %d) 0)"
                   % (BASE + i * 16, items, BASE + i * 16))
    for i, (form, label, enc) in enumerate(samps):
        out.append("/-- `%s` — %s (%s) -/" % (label, enc.hex(" "), form))
        out.append("example : (x86_step (X86State.init 10 %d) code_%d %d).isSome = true := by"
                   % (BASE + i * 16, i, BASE + i * 16))
        out.append("  native_decide")
    return "\n".join(out) + "\n"


def main():
    root = L._default_root()
    lean = L.find_lean(root)
    if not lean:
        print("lean not found (see ./lean-toolchain)")
        return 1
    lib = os.path.join(root, "lib")
    # THE LIBRARY ELABORATES, and it is worth saying out loud that this call is
    # that check. It was recorded for a long time as not being one: the
    # applicability rows below ask whether a lemma is APPLICABLE at a real
    # encoding, `x86_step_cqo`'s row among them, and a stale `cqo` lemma was
    # reported green by them while the library did not elaborate — because they
    # never touch the library's `.olean`, they generate their own file. It is
    # `ensure_library` that catches it, and it is here, at the top, before any
    # sample is even collected.
    #
    # `ensure_library` raises `RuntimeError` when `lean` returns non-zero, so a
    # `lib/X86.lean` that does not elaborate stops this script here rather than
    # at the first goal that needs it. That is the whole guard for a stale
    # lemma, and the reason the cqo incident took as long as it did to surface
    # is worth stating next to it: the failure first appeared in
    # `test_formal_dylib.py` and `test_formal_short_circuit_cond.py`, whose
    # messages are a truncated diagnostic tail, and neither names the line.
    L.ensure_library(lean, lib)

    samps = samples()
    # Guard the premise: a sample the decoder cannot read would make a
    # model-coverage failure mean something else entirely.
    undecodable = []
    for form, label, enc in samps:
        try:
            got = D.decode_one(enc, 0)
        except D.DecodeError as e:
            undecodable.append("%s (%s): decoder: %s" % (label, form, e))
            continue
        if got.form != form:
            undecodable.append("%s: decoder says %r, sample claims %r"
                               % (label, got.form, form))
    if undecodable:
        print("FAIL: the samples themselves do not decode — a coverage result "
              "would be meaningless")
        for u in undecodable:
            print("  " + u)
        return 1

    # A PRIVATE, self-removing directory, and ABSOLUTE paths handed to lean.
    # This used to be a hard-coded /tmp/x86_model_coverage shared by every run
    # of this script — see formal/lean.py::scratch_dir for what two concurrent
    # runs of it do to the 151-goal file that name points at.
    with L.scratch_dir("x86_model_coverage") as workdir:
        src = os.path.join(workdir, "Coverage.lean")
        with open(src, "w") as f:
            f.write(lean_source(samps))
        env = dict(os.environ, LEAN_PATH=os.pathsep.join((workdir, lib)))
        cp = L.run_lean(lean, [src], cwd=workdir, env=env,
                        wall_s=COVERAGE_WALL_S, cpu_s=COVERAGE_CPU_S)
        if cp.exceeded:
            print("FAIL: " + cp.exceeded)
            print("  coverage is UNMEASURED, not clean: a run that stopped "
                  "early has no encoding after the point it stopped, and "
                  "reporting those as 'the model steps them' is a green that "
                  "means nothing.")
            return 1
        text = cp.stdout + cp.stderr
        # The step lemmas, at real encodings.  A lemma the model can never be
        # asked about is the failure mode coverage above cannot see:
        # `x86_step` answers for every byte the encoder produces, and a lemma
        # whose hypotheses no such byte satisfies is a lemma that proves its
        # goal about nothing.
        lems = step_lemmas()
        ltext, checks = lemma_lean_source(lems)
        lname = "StepLemmas.lean"
        lpath = os.path.join(workdir, lname)
        with open(lpath, "w") as f:
            f.write(ltext)
        cp = L.run_lean(lean, [lpath], cwd=workdir, env=env,
                        wall_s=COVERAGE_WALL_S, cpu_s=COVERAGE_CPU_S)
        if cp.exceeded:
            print("\nFAIL: " + cp.exceeded)
            print("  lemma applicability is UNMEASURED, not satisfied: a "
                  "lemma whose `decide` never finished is exactly the "
                  "unsatisfiable-hypothesis case this half exists to find, and "
                  "reporting it as 'every hypothesis satisfiable' would hide "
                  "the finding.")
            return 1
        lout = cp.stdout + cp.stderr

        # The SUCCESSORS. `StepLemmas.lean` above asks whether each lemma's
        # hypotheses can hold at a real encoding; this asks whether the
        # successor the end-to-end emitter writes for that instruction is the
        # one the model computes. It is a separate file because a diagnostic in
        # it means a different thing — a wrong successor, not an inapplicable
        # lemma — and it has been needed: `cqo`'s `_SUCCS` row once named
        # `x86_sign_extend32` while the model's arm computes `x86_cqo`, which
        # left every hypothesis satisfiable and every `cqo` step a proof of a
        # different instruction.
        sforms = SUCCESSOR_FORMS
        stext, schecks = successor_lean_source(sforms)
        sname = "Successors.lean"
        spath = os.path.join(workdir, sname)
        with open(spath, "w") as f:
            f.write(stext)
        cp = L.run_lean(lean, [spath], cwd=workdir, env=env,
                        wall_s=COVERAGE_WALL_S, cpu_s=COVERAGE_CPU_S)
        if cp.exceeded:
            print("\nFAIL: " + cp.exceeded)
            print("  the successor check is UNMEASURED, not satisfied: a `decide` "
                  "that never finished is not a claim about the successor.")
            return 1
        sout = cp.stdout + cp.stderr
    unstepped = []
    for i, (form, label, enc) in enumerate(samps):
        if ("example : (x86_step (X86State.init 10 %d) code_%d" % (BASE + i * 16, i)) in text:
            unstepped.append((form, label, enc))
    forms = {f for f, _l, _e in samps}
    print("x86-64 model coverage: %d samples over %d forms — %s"
          % (len(samps), len(forms),
             "all steppable" if not unstepped
             else "%d NOT steppable" % len(unstepped)))
    for form, label, enc in unstepped:
        print("  x86_step returns none: %-14s %-24s [%s]"
              % (form, label, enc.hex(" ")))
    if unstepped:
        print("\nThe backend can emit these, so every program using one would "
              "stop mid-run in the model — and a stopped run reads as result 0 "
              "rather than as a failure.")
    rc = 1 if unstepped else 0

    bad = lemma_check_failures(lout, checks, lname)
    sbad = lemma_check_failures(sout, schecks, sname)
    print("\nemitted successor vs the model: %d form(s) — %s"
          % (len(sforms), "each successor is the model's"
             if not sbad else "%d of %d FAILED" % (len(sbad), len(schecks))))
    for label, why, where in sbad:
        print("  %-20s %s" % (label, why))
        print("      Lean reported it on line(s) %s of %s" % (where, sname))
    if sbad:
        rc = 1
    print("\nstep-lemma applicability: %d lemma(s) at %d real encoding(s), %d "
          "hypotheses — %s"
          % (len({l.lemma for l in lems}), len(lems), len(checks),
             "every hypothesis satisfiable" if not bad
             else "%d of %d FAILED" % (len(bad), len(checks))))
    for label, why, where in bad:
        print("  %-20s %s" % (label, why))
        print("      Lean reported it on line(s) %s of %s" % (where, lname))
    if bad:
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
