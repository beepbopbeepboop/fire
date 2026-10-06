#!/usr/bin/env python3
"""Every x86-64 encoder round-trips through formal/x86_64_decode.

The decoder in `formal/x86_64_decode.py` is a claim about the byte stream: that
it can find instruction boundaries and name each instruction's form. An
untested decoder that silently mis-decodes is worse than none, because the
machine model in lib/ProofLib.lean is then extended and trusted on the
strength of it. This test pins the claim to the encoders it is the inverse of:
for each `encode_*` in formal/x86_64.py, decode the bytes it produces and
check the form and operands come back.

It also builds THIS MODULE through the formal backend at the end, because the
decoder is swept like any other source file and its first two refusals were
about what it DECLARES rather than about what it computes — `Insn.extra`'s
`field(default_factory=dict)`, which nothing reads, and `DecodeError(msg)`,
which is a construction with one argument and a struct that declared no slot to
put it in. Neither is visible to a round-trip.

Run: python3 test_x86_64_decode.py
"""

import struct
import sys

import formal.x86_64 as X
import formal.x86_64_decode as D

FAILURES = []


def check(name, encoded, want_form, **want):
    try:
        insn = D.decode_one(encoded, 0)
    except D.DecodeError as e:
        FAILURES.append(f"{name}: decode failed: {e}")
        return
    if insn.form != want_form:
        FAILURES.append(f"{name}: form {insn.form!r} != {want_form!r} "
                        f"(bytes {encoded.hex()})")
        return
    if insn.length != len(encoded):
        FAILURES.append(f"{name}: length {insn.length} != {len(encoded)} "
                        f"(bytes {encoded.hex()})")
    for field, value in want.items():
        got = getattr(insn, field)
        if got != value:
            FAILURES.append(f"{name}: {field} {got!r} != {value!r} "
                            f"(bytes {encoded.hex()})")


R = X.Reg

# push / pop / ret / leave / nop
for reg in (R.RAX, R.RCX, R.RSP, R.RBP, R.R8, R.R12, R.R15):
    check(f"push {reg.name}", X.encode_push_r64(reg), "push_r64", rm=reg.value)
    check(f"pop {reg.name}", X.encode_pop_r64(reg), "pop_r64", rm=reg.value)
check("ret", X.encode_ret(), "ret")
check("leave", X.encode_leave(), "leave")
check("nop", X.encode_nop(), "nop")

# mov
check("mov rax,imm32", X.encode_mov_r64_imm32(R.RAX, 0x41), "mov_rm64_imm32",
      rm=R.RAX.value, imm=0x41)
check("mov r12,imm32", X.encode_mov_r64_imm32(R.R12, -5), "mov_rm64_imm32",
      rm=R.R12.value, imm=-5)
check("mov rax,imm64", X.encode_mov_r64_imm64(R.RAX, 1 << 40), "mov_r64_imm64",
      rm=R.RAX.value, imm=1 << 40)
check("mov r9,imm64", X.encode_mov_r64_imm64(R.R9, 0xDEADBEEF), "mov_r64_imm64",
      rm=R.R9.value, imm=0xDEADBEEF)
check("mov rbp,rsp", X.encode_mov_r64_r64(R.RBP, R.RSP), "mov_rm64_r64",
      mod=3, reg=R.RSP.value, rm=R.RBP.value)
check("mov r13,r14", X.encode_mov_r64_r64(R.R13, R.R14), "mov_rm64_r64",
      mod=3, reg=R.R14.value, rm=R.R13.value)
check("mov rax,[rbx]", X.encode_mov_r64_rm64(R.RAX, R.RBX), "mov_r64_rm64",
      mem_base=R.RBX.value, mem_disp=0)
check("mov rax,[rbp+16]", X.encode_mov_r64_rm64(R.RAX, R.RBP, 16),
      "mov_r64_rm64", mem_base=R.RBP.value, mem_disp=16)
check("mov rax,[rsp+8]", X.encode_mov_r64_rm64(R.RAX, R.RSP, 8),
      "mov_r64_rm64", mem_base=R.RSP.value, mem_disp=8)
check("mov r12,[rsp+300]", X.encode_mov_r64_rm64(R.R12, R.RSP, 300),
      "mov_r64_rm64", mem_base=R.RSP.value, mem_disp=300)
check("mov rax,[r13-0x1000]", X.encode_mov_r64_rm64(R.RAX, R.R13, -0x1000),
      "mov_r64_rm64", mem_base=R.R13.value, mem_disp=-0x1000)
check("mov [rbp-8],rax", X.encode_mov_rm64_r64(R.RBP, -8, R.RAX), "mov_rm64_r64",
      mem_base=R.RBP.value, mem_disp=-8)
check("mov [rsp+16],r10", X.encode_mov_rm64_r64(R.RSP, 16, R.R10), "mov_rm64_r64",
      mem_base=R.RSP.value, mem_disp=16)
check("mov eax,edx", X.encode_mov_r32_r32(R.RAX, R.RDX), "mov_rm32_r32",
      mod=3, reg=R.RDX.value, rm=R.RAX.value)
check("mov r8d,r9d", X.encode_mov_r32_r32(R.R8, R.R9), "mov_rm32_r32",
      mod=3, reg=R.R9.value, rm=R.R8.value)
check("movsxd rax,edx", X.encode_movsx_r64_r32(R.RAX, R.RDX), "movsxd_r64_r32",
      mod=3, reg=R.RAX.value, rm=R.RDX.value)
check("movzx rax,dl", X.encode_movzx_r64_r8(R.RAX, R.RDX), "movzx_r64_r8",
      mod=3, reg=R.RAX.value, rm=R.RDX.value)
check("movsx r10,r11b", X.encode_movsx_r64_r8(R.R10, R.R11), "movsx_r64_r8",
      mod=3, reg=R.R10.value, rm=R.R11.value)
check("movzx rax,dx", X.encode_movzx_r64_r16(R.RAX, R.RDX), "movzx_r64_r16")
check("movsx rax,dx", X.encode_movsx_r64_r16(R.RAX, R.RDX), "movsx_r64_r16")

# ── the pointee-WIDTH memory forms ───────────────────────────────────
#
# Eight encoders the model steps and this decoder used to REFUSE, which is a
# worse state than not knowing them: `formal/x86_64_model_coverage_test.py` runs
# every sample through this decoder first and reports a decode failure as a
# DECODER failure, so a sample naming one of these could never become a coverage
# row — the coverage question was never asked. All eight are `samples()` rows
# now, and the coverage run reports 183 samples over 66 forms with every one of
# them steppable by `x86_step` (1.3 GB, through `formal/lean.py::run_lean`).
#
# Why each one exists is `formal/x86_64.py`'s, and it is the same reason for all
# eight: an 8-byte access to a 1-, 2- or 4-byte pointee over-reads or
# over-writes it. Every row below is checked for `mem_base`/`mem_disp` as well
# as for the form and the LENGTH, because the length is the part these forms got
# wrong — `88 /r` is three bytes and `66 REX 89 /r` is four, so a decoder that
# resumed at a fixed offset walked into the displacement, and a decoder that
# named the register form's successor for a memory encoding produced a
# successor about a different instruction that still typechecked.
#
# Both operand kinds are pinned for the families that have both, and they are
# DIFFERENT names: `movzx_r64_r8` reads RDX, `movzx_r64_rm8` reads memory. The
# split is the operand kind and NOT REX.W, because `encode_movzx_r64_rm8` emits
# `0F B6` with no REX.W at all (the destination is written as a 32-bit register,
# which zero-extends) while `encode_movsx_r64_rm8` emits REX.W `0F BE`.
for _base, _disp in ((R.RBX, 0), (R.RBP, 8), (R.R13, 300), (R.RSP, 16),
                     (R.R12, 128)):
    _w = "mov %s%s, ..." % (_base.name,
                            "" if _disp == 0 else "%+d" % _disp)
    check("mov byte [%s], sil" % _w,
          X.encode_mov_rm8_r8(_base, _disp, R.RSI), "mov_rm8_r8",
          mem_base=_base.value, mem_disp=_disp)
    check("mov word [%s], r11w" % _w,
          X.encode_mov_rm16_r16(_base, _disp, R.R11), "mov_rm16_r16",
          mem_base=_base.value, mem_disp=_disp)
    check("mov dword [%s], r11d" % _w,
          X.encode_mov_rm32_r32(_base, _disp, R.R11), "mov_rm32_r32_mem",
          mem_base=_base.value, mem_disp=_disp)
    check("mov eax, [%s]" % _w,
          X.encode_mov_r32_rm32(R.RAX, _base, _disp), "mov_r32_rm32",
          mem_base=_base.value, mem_disp=_disp)
    check("movzx rax, byte [%s]" % _w,
          X.encode_movzx_r64_rm8(R.RAX, _base, _disp), "movzx_r64_rm8",
          mem_base=_base.value, mem_disp=_disp)
    check("movzx r11, word [%s]" % _w,
          X.encode_movzx_r64_rm16(R.R11, _base, _disp), "movzx_r64_rm16",
          mem_base=_base.value, mem_disp=_disp)
    check("movsx r9, byte [%s]" % _w,
          X.encode_movsx_r64_rm8(R.R9, _base, _disp), "movsx_r64_rm8",
          mem_base=_base.value, mem_disp=_disp)
    check("movsx rax, word [%s]" % _w,
          X.encode_movsx_r64_rm16(R.RAX, _base, _disp), "movsx_r64_rm16",
          mem_base=_base.value, mem_disp=_disp)
    check("movsxd rax, dword [%s]" % _w,
          X.encode_movsx_r64_rm32(R.RAX, _base, _disp), "movsx_r64_rm32",
          mem_base=_base.value, mem_disp=_disp)
# A four-byte displacement and a high base on the byte store, which is the pair
# that makes the instruction SIX bytes and so the one a `+ 3` arithmetic gets
# wrong in a way a small-displacement row cannot see.
check("mov byte [rbp-0x410], dil",
      X.encode_mov_rm8_r8(R.RBP, -0x410, R.RDI), "mov_rm8_r8",
      mem_base=R.RBP.value, mem_disp=-0x410)
check("mov word [r13+4096], r11w",
      X.encode_mov_rm16_r16(R.R13, 4096, R.R11), "mov_rm16_r16",
      mem_base=R.R13.value, mem_disp=4096)
# And the register forms of the two families that have both, pinned by NAME so a
# decoder that stopped distinguishing them would have to change one of these.
check("movzx rax, dl", X.encode_movzx_r64_r8(R.RAX, R.RDX), "movzx_r64_r8",
      mod=3)
check("movsxd rax, edx", X.encode_movsx_r64_r32(R.RAX, R.RDX),
      "movsxd_r64_r32", mod=3)
check("mov r11d, [rax]", X.encode_mov_rm32_r32(R.RAX, 0, R.R11),
      "mov_rm32_r32_mem", mem_base=R.RAX.value, mem_disp=0)

# `movq xmm, r64` — the GPR-to-SSE move, and the first instruction this project
# emits into a formal image that crosses from one register FILE into another.
# SysV AMD64 hands a `double` to a variadic callee in XMM0..XMM7 and nowhere
# else, so `printf("%f", w)` cannot be lowered without it.
#
# EVERY (xmm, gpr) pair, not one: the two index extensions are independent and
# a single row cannot see either of them go wrong. The XMM number comes from the
# ModRM `reg` field with NO REX.R (there is no XMM8 in this ABI, and
# `encode_movq_xmm_rm64` asserts `0 <= xmm <= 7`), while the source GPR comes
# from `rm` WITH REX.B. `xmm0`/`rax` is the pair where both are zero, so a
# decoder that dropped REX.B and put REX.R on the XMM index would still pass
# there. `xmm3`/`r12` is the row that separates them: a dropped REX.B names RSP
# and a wrongly-applied REX.R names XMM11.
for xmm in range(8):
    for gpr in (R.RAX, R.R9, R.RDI, R.R12, R.R8):
        check(f"movq xmm{xmm},{gpr.name}",
              X.encode_movq_xmm_rm64(xmm, gpr), "movq_xmm_rm64",
              mod=3, xmm=xmm, rm=gpr.value)
# The XMM number is read off the RAW ModRM byte and not through the helper that
# applies REX.R to `reg`, so `xmm` and `reg` are both the raw field. Asserting it
# here is what says the two readers of an instruction agree about which half of
# the ModRM is which; `x86_step_op66` reads `(modrm >>> 3) &&& 7` for the same
# field, and the direction is the opposite of `89 /r`.
check("movq xmm7,rsp", X.encode_movq_xmm_rm64(7, R.RSP), "movq_xmm_rm64",
      mod=3, xmm=7, reg=7, rm=R.RSP.value)

# THE THREE SHAPES THAT MUST STILL BE REFUSED, and each for a stated reason.
# Without these the decoder could accept `0F 7E` (the REVERSE move, which
# assembles and links and quietly loads whatever was already in XMM0 into RDI)
# or `0F 6E` without REX.W (`MOVD`, which drops all but the low 32 bits and so
# moves a different VALUE rather than a different placement of the same one),
# and both would then be proved against an instruction this backend cannot emit.
for label, raw, why in (
        ("movq xmm,m64 (memory operand)", bytes([0x66, 0x48, 0x0F, 0x6E, 0x00]),
         "mod=0 is a memory operand, which no emit path produces"),
        ("0F 7E (the reverse move)", bytes([0x66, 0x48, 0x0F, 0x7E, 0xC0]),
         "the reverse direction is not emitted and must not be inferred"),
        ("MOVD, no REX.W", bytes([0x66, 0x0F, 0x6E, 0xC0]),
         "without REX.W this is MOVD, a different value"),
        ("0F 6E with no 0x66 prefix", bytes([0x48, 0x0F, 0x6E, 0xC0]),
         "a four-byte instruction, and not one this backend emits")):
    try:
        got = D.decode_one(raw, 0)
        FAILURES.append(f"{label}: decoded as {got.form!r} — {why}")
    except D.DecodeError:
        pass

# ALU reg/reg
for enc, name in ((X.encode_add_r64_r64, "add"), (X.encode_or_r64_r64, "or"),
                  (X.encode_and_r64_r64, "and"), (X.encode_sub_r64_r64, "sub"),
                  (X.encode_xor_r64_r64, "xor"), (X.encode_cmp_r64_r64, "cmp"),
                  (X.encode_test_r64_r64, "test")):
    check(f"{name} r10,r11", enc(R.R10, R.R11), f"alu_rr:{name}",
          mod=3, reg=R.R11.value, rm=R.R10.value)
    check(f"{name} rax,rbx", enc(R.RAX, R.RBX), f"alu_rr:{name}",
          mod=3, reg=R.RBX.value, rm=R.RAX.value)
check("imul rax,rbx", X.encode_imul_r64_r64(R.RAX, R.RBX), "imul_r64_r64",
      mod=3, reg=R.RAX.value, rm=R.RBX.value)

# ALU reg/imm
for enc, name in ((X.encode_add_r64_imm32, "add"), (X.encode_or_r64_imm32, "or"),
                  (X.encode_and_r64_imm32, "and"), (X.encode_sub_r64_imm32, "sub"),
                  (X.encode_xor_r64_imm32, "xor"), (X.encode_cmp_r64_imm32, "cmp")):
    check(f"{name} rax,1000", enc(R.RAX, 1000), f"alu_ri32:{name}",
          mod=3, rm=R.RAX.value, imm=1000)
    check(f"{name} r10,-7", enc(R.R10, -7), f"alu_ri32:{name}",
          mod=3, rm=R.R10.value, imm=-7)
for enc, name in ((X.encode_add_r64_imm8, "add"), (X.encode_and_r64_imm8, "and"),
                  (X.encode_sub_r64_imm8, "sub"), (X.encode_cmp_r64_imm8, "cmp")):
    check(f"{name} rax,7", enc(R.RAX, 7), f"alu_ri8:{name}",
          mod=3, rm=R.RAX.value, imm=7)
    check(f"{name} r9,-3", enc(R.R9, -3), f"alu_ri8:{name}",
          mod=3, rm=R.R9.value, imm=-3)

# unary / multiply-divide
for enc, name in ((X.encode_neg_r64, "neg"), (X.encode_not_r64, "not"),
                  (X.encode_mul_r64, "mul"), (X.encode_imul_r64_1op, "imul1"),
                  (X.encode_div_r64, "div"), (X.encode_idiv_r64, "idiv")):
    check(f"{name} rax", enc(R.RAX), f"group3:{name}", mod=3, rm=R.RAX.value)
    check(f"{name} r11", enc(R.R11), f"group3:{name}", mod=3, rm=R.R11.value)
check("cqo", X.encode_cqo(), "cqo")
check("xor edx,edx", X.encode_xor_edx_edx(), "alu_rr32:xor", mod=3,
      reg=R.RDX.value, rm=R.RDX.value)

# shifts
for op, name in (("<<", "shl"), (">>", "shr"), (">>signed", "sar")):
    check(f"{name} rax,3", X.encode_shift_r64_imm8(op, R.RAX, 3),
          f"shift_imm8:{name}", mod=3, rm=R.RAX.value, imm=3)
    check(f"{name} r9,cl", X.encode_shift_r64_cl(op, R.R9), f"shift_cl:{name}",
          mod=3, rm=R.R9.value)

# lea
check("lea rax,[rbx+8]", X.encode_lea_r64_rm64(R.RAX, R.RBX, 8), "lea_r64_rm64",
      mem_base=R.RBX.value, mem_disp=8)
check("lea r10,[rsp+32]", X.encode_lea_r64_rm64(R.R10, R.RSP, 32), "lea_r64_rm64",
      mem_base=R.RSP.value, mem_disp=32)
check("lea rax,[rip+16]", X.encode_lea_r64_rip(R.RAX, 16), "lea_r64_rip", rip_rel=16)
check("lea r10,[rip+0]", X.encode_lea_r64_rip(R.R10, 0), "lea_r64_rip", rip_rel=0)

# setcc
for enc, name in ((X.encode_sete, "sete"), (X.encode_setne, "setne"),
                  (X.encode_setl, "setl"), (X.encode_setle, "setle"),
                  (X.encode_setg, "setg"), (X.encode_setge, "setge"),
                  (X.encode_setb, "setb"), (X.encode_setbe, "setbe"),
                  (X.encode_seta, "seta"), (X.encode_setae, "setae")):
    check(f"{name} al", enc(R.RAX), "setcc", mod=3, rm=R.RAX.value)
    check(f"{name} r11b", enc(R.R11), "setcc", mod=3, rm=R.R11.value)

# branches and calls
for cc in (0, 1, 2, 4, 5, 6, 7, 10):
    check(f"jcc rel8 cc={cc}", X.encode_jcc_rel8(cc, 5), "jcc_rel8", cc=cc, imm=5)
    check(f"jcc rel32 cc={cc}", X.encode_jcc_rel32(cc, -70), "jcc_rel32",
          cc=cc, imm=-70)
check("jmp rel8", X.encode_jmp_rel8(-3), "jmp_rel8", imm=-3)
check("jmp rel32", X.encode_jmp_rel32(0x1234), "jmp_rel32", imm=0x1234)
check("call rel32", X.encode_call_rel32(-0x2000), "call_rel32", imm=-0x2000)
check("call [rip+x]", X.encode_call_rm64(0x40), "call_rm64", rip_rel=0x40)
check("jmp [rip+x]", X.encode_jmp_rm64(-0x30), "jmp_rm64", rip_rel=-0x30)

# A back-to-back stream decodes as a sequence, not just instruction by
# instruction: boundaries are the whole point of the decoder.
STREAM = (X.encode_push_r64(R.RBP) + X.encode_mov_r64_r64(R.RBP, R.RSP)
          + X.encode_mov_r64_imm32(R.RDI, 10) + X.encode_call_rel32(11)
          + X.encode_pop_r64(R.RBP) + X.encode_ret())
try:
    insns = D.decode_all(STREAM)
    if [i.form for i in insns] != ["push_r64", "mov_rm64_r64", "mov_rm64_imm32",
                                   "call_rel32", "pop_r64", "ret"]:
        FAILURES.append(f"stream forms: {[i.form for i in insns]}")
    if [i.next_offset for i in insns] != [1, 4, 11, 16, 17, 18]:
        FAILURES.append(f"stream boundaries: {[i.next_offset for i in insns]}")
except D.DecodeError as e:
    FAILURES.append(f"stream: decode failed: {e}")

# Nothing that is not an instruction may decode silently: the data pool at the
# end of an image must be rejected, not interpreted.
try:
    D.decode_all(b"hello world\0")
    FAILURES.append("data bytes decoded as instructions (they must not)")
except D.DecodeError:
    pass

# ── the two DECLARATIONS the formal backend builds this module through ──────
#
# `formal/x86_64_decode.py` is itself swept by `tools/formal_sweep.py`, and its
# first two refusals were about what it DECLARES rather than about what it
# computes, so a round-trip above cannot see them: every case here builds or
# decodes fine in CPython either way.
#
#   * `Insn.extra` was `field(default_factory=dict)` and is read and written
#     NOWHERE in the repository — the `extra` names in this module are a local
#     counting trailing bytes. So there is no per-instance value for a factory
#     to produce, and the declaration described nothing the program does.
#   * `DecodeError(msg)` is a construction with one argument, and a struct that
#     declares no field of its own has no slot to put it in: the fields are
#     filled in DECLARATION ORDER from positional arguments. It declares
#     `args` now, which is the field CPython's `BaseException` already fills
#     from those arguments and `str(e)` already reads.
#
# The build below is the assertion that matters: the file's FIRST refusal must
# not be either construct. It is a build and not a source inspection because
# the two are only related by the backend's reading of the declarations — the
# whole content of both fixes is what that reading sees.
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")


def _formal_first_refusal(rel):
    """The first refusal `fire.py build --formal` prints for `rel`, or ''.

    Both architectures, and both answers are needed: a refusal that only one of
    them reaches is one this test would otherwise call green. '' means the file
    BUILDS, which is strictly better than either needle and says so.
    """
    out = []
    for backend in ("arm64", "x86_64"):
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             f"--backend={backend}", "-o",
             os.path.join(HERE, "build", f"decode_sweep_{backend}"),
             os.path.join(HERE, rel)],
            capture_output=True, text=True, timeout=600, cwd=HERE)
        out.append("" if r.returncode == 0
                   else (r.stderr or r.stdout).strip())
    return out


for _msg in _formal_first_refusal("formal/x86_64_decode.py"):
    if "default_factory" in _msg:
        FAILURES.append("formal/x86_64_decode.py is refused on "
                        "`field(default_factory=…)` again: " + _msg[-300:])
    if "constructing DecodeError" in _msg:
        FAILURES.append("formal/x86_64_decode.py is refused on constructing "
                        "DecodeError again — it declares `args`, so the message "
                        "has a slot: " + _msg[-300:])
# And the declarations themselves, so a fix that deleted the message instead of
# the cause would still be caught: `str()` reads `args` on both paths.
try:
    if str(D.DecodeError("truncated instruction at 4")) != \
            "truncated instruction at 4":
        FAILURES.append("DecodeError lost its message: `str(e)` does not read "
                        "the argument the raise passed")
except Exception as _e:                                    # noqa: BLE001
    FAILURES.append(f"DecodeError could not be raised with a message: {_e}")

if FAILURES:
    print(f"FAIL ({len(FAILURES)})")
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ok: every x86-64 encoder round-trips through the decoder")
