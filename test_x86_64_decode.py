#!/usr/bin/env python3
"""Every x86-64 encoder round-trips through formal/x86_64_decode.

The decoder in `formal/x86_64_decode.py` is a claim about the byte stream: that
it can find instruction boundaries and name each instruction's form. An
untested decoder that silently mis-decodes is worse than none, because the
machine model in lib/ProofLib.lean is then extended and trusted on the
strength of it. This test pins the claim to the encoders it is the inverse of:
for each `encode_*` in formal/x86_64.py, decode the bytes it produces and
check the form and operands come back.

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

if FAILURES:
    print(f"FAIL ({len(FAILURES)})")
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ok: every x86-64 encoder round-trips through the decoder")
