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
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import formal.x86_64 as X                                # noqa: E402
import formal.x86_64_decode as D                         # noqa: E402
import formal.lean as L                                  # noqa: E402

R = X.Reg
BASE = 0x1000
"""Where samples are placed. Any address works — the model addresses the code
function absolutely — but a round one makes a failure readable."""


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


def _rex_0f_mod3_hyps(addr, rex, modrm, reg, rm, dst, op2):
    """Hypotheses for a `REX 0F <op2> /r` mod=3 instruction, concretised.

    Shared by every form below that is `REX.W 0F xx /r` with a register
    operand, because those are the ones whose hypotheses a generator reads out
    of the encoding rather than computes.  `reg`/`rm`/`dst` are the ModRM and
    REX fields already resolved to the names the lemmas use, and the caller
    passes them so this stays a transcription of the lemma's statement rather
    than a second derivation of it.

    The `(x : UInt8).toNat` ascription is not decoration, twice over.  Lean
    reads `192.toNat` as a malformed decimal — a PARSE error, and in a check
    file a parse error is a check that did not run — and `(192).toNat` parses but
    elaborates `192` as a `Nat`, which has no `toNat` field, so the hypothesis
    is an elaboration error instead.  The ascription is what makes it the same
    expression the lemma states about a `UInt8` ModRM byte.
    """
    b = "(%d : UInt8).toNat" % modrm
    return [
        "s.rip = %d" % addr,
        "code %d = %d" % (addr, rex),
        "code %d = %d" % (addr + 1, 0x0f),
        "code %d = %d" % (addr + 2, op2),
        "code %d = %d" % (addr + 3, modrm),
        "x86_is_rex %d = true" % rex,
        "x86_rex_w %d = true" % rex,
        "%s >>> 6 = 3" % b,
        "(%s >>> 3) &&& 7 = %d" % (b, reg),
        "%s &&& 7 = %d" % (b, rm),
        "%d + x86_rex_r %d = %d" % (reg, rex, dst),
    ]


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
            _rex_0f_mod3_hyps(BASE + 16 * len(out), rex, modrm, reg, rm, d,
                              0xbe)))
    return out


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

    The file name is compared rather than assumed, because Lean prints the path
    it was given and a caller elsewhere in this file passes an absolute one.
    """
    at = set()
    for m in _LEAN_LOC.finditer(out):
        if m.group(1) == filename:
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

    workdir = os.path.join("/tmp", "x86_model_coverage")
    os.makedirs(workdir, exist_ok=True)
    src = os.path.join(workdir, "Coverage.lean")
    with open(src, "w") as f:
        f.write(lean_source(samps))
    env = dict(os.environ, LEAN_PATH=os.pathsep.join((workdir, lib)))
    cp = subprocess.run([lean, os.path.basename(src)], cwd=workdir, env=env,
                        capture_output=True, text=True, timeout=3600)
    text = cp.stdout + cp.stderr
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

    # The step lemmas, at real encodings.  A lemma the model can never be asked
    # about is the failure mode coverage above cannot see: `x86_step` answers
    # for every byte the encoder produces, and a lemma whose hypotheses no such
    # byte satisfies is a lemma that proves its goal about nothing.
    lems = step_lemmas()
    ltext, checks = lemma_lean_source(lems)
    lname = "StepLemmas.lean"
    with open(os.path.join(workdir, lname), "w") as f:
        f.write(ltext)
    cp = subprocess.run([lean, lname], cwd=workdir, env=env,
                        capture_output=True, text=True, timeout=3600)
    bad = lemma_check_failures(cp.stdout + cp.stderr, checks, lname)
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
