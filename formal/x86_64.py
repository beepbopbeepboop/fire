#!/usr/bin/env python3
"""x86-64 (AMD64) instruction encoder and assembler.

Ported from /Users/mrs/net/chatgpt/claude/formal/compiler/x86_64.py, the toy
formal compiler's x86-64 backend, and extended to the instruction set the
fire_compiler-facing formal codegen (formal/x86_64_codegen.py) needs: the
64-bit ALU/shift/divide forms, the memory-operand forms, and rel32 branches
throughout.

Everything here is little-endian. x86-64 instructions are variable width
(1-15 bytes), so the `Assembler` records label fixups as (position, kind)
rather than assuming a fixed stride the way the arm64 assembler can.

Naming convention mirrors formal/arm64.py: `encode_<mnemonic>_<operands>`,
`Reg` for the 16 general-purpose registers, and `Assembler` with
`org`/`label`/`emit`/`resolve`.
"""

import struct
from enum import Enum

from formal.model import CodegenError


class Reg(Enum):
    RAX = 0
    RCX = 1
    RDX = 2
    RBX = 3
    RSP = 4
    RBP = 5
    RSI = 6
    RDI = 7
    R8 = 8
    R9 = 9
    R10 = 10
    R11 = 11
    R12 = 12
    R13 = 13
    R14 = 14
    R15 = 15


# Condition codes as used by Jcc / SETcc. Indexed by the low nibble of the
# 0x0F 0x8x / 0x0F 0x9x opcode.
COND_O = 0x0
COND_NO = 0x1
COND_B = 0x2        # unsigned below  (CF=1)   — aka C / NAE
COND_AE = 0x3       # unsigned above-or-equal    — aka NC / NB
COND_E = 0x4        # equal          (ZF=1)
COND_NE = 0x5
COND_BE = 0x6       # unsigned below-or-equal
COND_A = 0x7        # unsigned above
COND_S = 0x8
COND_NS = 0x9
COND_P = 0xA
COND_NP = 0xB
COND_L = 0xC        # signed less     (SF != OF) — aka NGE
COND_GE = 0xD       # signed greater-or-equal
COND_LE = 0xE       # signed less-or-equal
COND_G = 0xF        # signed greater


# formal's x86-64 calling convention (System V AMD64 integer argument order).
# Chosen to match the host ABI so the extern path (printf/exit via dyld or the
# ELF dynamic linker) needs no thunk.
ARG_REGS = (Reg.RDI, Reg.RSI, Reg.RDX, Reg.RCX, Reg.R8, Reg.R9)
RETURN_REG = Reg.RAX
# Callee-saved by the System V AMD64 ABI, so a plain `call` from an extern
# (libSystem) cannot clobber a local living in one. RSP/RBP are the frame.
CALLEE_SAVED = (Reg.RBX, Reg.R12, Reg.R13, Reg.R14, Reg.R15)
# Caller-saved scratch: R10/R11 are safe to clobber inside a subexpression and
# hold no local. RDX is deliberately NOT listed: it is the high half of the
# dividend for the one-operand divide forms (see encode_cqo / encode_idiv_r64),
# so the codegen keeps it clear of anything that has to survive an expression.
SCRATCH_REGS = (Reg.R10, Reg.R11)


def _rex(w: int = 0, r: int = 0, x: int = 0, b: int = 0) -> int:
    return 0x40 | (w << 3) | (r << 2) | (x << 1) | b


def _modrm(mod: int, reg: int, rm: int) -> int:
    return (mod << 6) | ((reg & 7) << 3) | (rm & 7)


def _rm_disp(base: Reg, disp: int) -> tuple:
    """`mod` field plus displacement bytes for `[base + disp]`.

    x86 addresses a base register either directly (mod=00, no displacement) or
    through a disp8/disp32 (mod=01/10). `[RBP]`/`[R13]` are the two low-
    encodable registers that have no disp=0 form — mod=00 with rm=5 means
    RIP-relative — so they always carry at least a disp8."""
    if disp == 0 and base.value != Reg.RBP.value:
        return 0, b""
    if -128 <= disp <= 127:
        return 1, bytes([disp & 0xFF])
    return 2, struct.pack("<i", disp)


def _sib(base: Reg) -> bytes:
    """SIB byte for a base register that needs one (RSP/R12 as base).

    rm=4 in the ModRM byte selects a SIB byte rather than naming RSP, so any
    memory operand based on RSP (or R12, which shares the low bits) has to
    carry one. The SIB's index field is 4 (= none, no index) and its scale is
    1; the base field names the real register."""
    return bytes([0x20 | (base.value & 7)])


def _mem_operand(base: Reg, disp: int) -> tuple:
    """(mod, rm, extra_bytes) for a memory operand `[base + disp]`.

    `extra_bytes` is the SIB byte (when rm=4 selects one) FOLLOWED by the
    displacement — the SIB sits between the ModRM byte and the displacement in
    the instruction stream, not after it."""
    mod, disp_bytes = _rm_disp(base, disp)
    if (base.value & 7) == Reg.RSP.value:
        return mod, 4, _sib(base) + disp_bytes
    return mod, base.value & 7, disp_bytes


def _mem_modrm(base: Reg, disp: int, reg: Reg) -> tuple:
    """(modrm byte, extra bytes) for `[base + disp]` with `reg` in the
    ModRM reg field."""
    mod, rm, extra = _mem_operand(base, disp)
    return _modrm(mod, reg.value & 7, rm), extra


# ── push / pop / ret / leave ──────────────────────────────────────────

def encode_push_r64(reg: Reg) -> bytes:
    assert Reg.RAX.value <= reg.value <= Reg.R15.value
    if reg.value < 8:
        return bytes([0x50 | reg.value])
    return bytes([0x41, 0x50 | (reg.value & 7)])


def encode_pop_r64(reg: Reg) -> bytes:
    assert Reg.RAX.value <= reg.value <= Reg.R15.value
    if reg.value < 8:
        return bytes([0x58 | reg.value])
    return bytes([0x41, 0x58 | (reg.value & 7)])


def encode_ret() -> bytes:
    return bytes([0xC3])


def encode_leave() -> bytes:
    """mov rsp, rbp ; pop rbp — the epilogue paired with push rbp / mov rbp,rsp."""
    return bytes([0xC9])


def encode_nop() -> bytes:
    return bytes([0x90])


# ── mov ──────────────────────────────────────────────────────────────

def encode_mov_r64_imm32(reg: Reg, imm: int) -> bytes:
    """mov reg, imm32 (sign-extended to 64 bits) — C7 /0 id."""
    assert -2**31 <= imm < 2**31
    enc = [_rex(w=1, b=1 if reg.value >= 8 else 0), 0xC7]
    enc.append(_modrm(3, 0, reg.value & 7))
    enc.extend(struct.pack("<i", imm))
    return bytes(enc)


def encode_mov_r64_imm64(reg: Reg, imm: int) -> bytes:
    """mov reg, imm64 — REX.W B8+r io.

    `imm` is the whole 64-bit PATTERN, which is what the caller hands over
    (`X86_64Codegen._emit_mov_imm` masks to 64 bits before choosing this form)
    and what the `assert` below states: -2**63 <= imm < 2**64, unsigned top
    included. It is packed UNSIGNED for that reason. `struct.pack("<q", …)`
    raises `struct.error` — an unhandled exception, i.e. a compiler CRASH
    rather than a refusal — for any pattern with bit 63 set, which is every
    constant in [2**63, 2**64) and so every 64-bit hash IV above 2**63:
    BLAKE2b's `IV1` (0xbb67ae8584caa73b) is one, and `formal/hostmods/
    hashlib.mojo` could not be built for x86-64 until this was fixed. The ten
    bytes are the same either way — a signed pack of the same bits is the same
    little-endian pattern — so the unsigned pack is a fix and not a choice
    between two answers.
    """
    assert -2**63 <= imm < 2**64
    rex = _rex(w=1, b=1 if reg.value >= 8 else 0)
    enc = [rex, 0xB8 | (reg.value & 7)]
    enc.extend(struct.pack("<Q", imm & 0xFFFFFFFFFFFFFFFF))
    return bytes(enc)


def encode_mov_r64_r64(dst: Reg, src: Reg) -> bytes:
    """mov dst, src — REX.W 89 /r (r/m gets the reg operand)."""
    rex = _rex(w=1, r=1 if src.value >= 8 else 0,
               b=1 if dst.value >= 8 else 0)
    return bytes([rex, 0x89, _modrm(3, src.value & 7, dst.value & 7)])


def encode_movq_xmm_rm64(xmm: int, src: Reg) -> bytes:
    """movq xmm<k>, r64 — 66 REX.W 0F 7E /r, the GPR-to-SSE move.

    **Why this instruction exists at all**, because nothing else on this path
    crosses that boundary: a value here is one 64-bit word and it lives in a
    general-purpose register, and the SysV AMD64 ABI hands a `double` to a
    variadic callee in `XMM0`..`XMM7` and nowhere else. So a `printf("%f", w)`
    whose word is in `RDI` reads whatever `XMM0` happened to contain — which is
    why the wrong answer was a DENORMAL and why it CHANGED BETWEEN RUNS of the
    same binary rather than merely being wrong.

    The encoding is `66 REX.W 0F 6E /r` and the direction matters, because the
    two moves share a ModRM shape and differ only in which half is the XMM:
    `0F 6E` is `MOVQ xmm, r/m64` (XMM in the reg field, GPR in r/m — the
    direction wanted here) and `0F 7E` is `MOVQ r/m64, xmm` (the reverse, which
    assembles, links and quietly loads whatever was already in XMM0 into RDI).
    The width modifiers are load-bearing for the same reason: `0F 6E` without
    REX.W is `MOVD`, which drops all but the low 32 bits and so moves a
    DIFFERENT VALUE rather than a different placement of the same one.

    `xmm` is the XMM number 0..7 and is the low three bits of ModRM.reg; there
    is no REX.R because no XMM register is numbered 8 or above in this ABI, and
    the B bit carries the GPR's own extension.
    """
    assert 0 <= xmm <= 7
    assert isinstance(src, Reg)
    rex = _rex(w=1, b=1 if src.value >= 8 else 0)
    return bytes([0x66, rex, 0x0F, 0x6E, _modrm(3, xmm, src.value & 7)])


def encode_mov_r64_rm64(dst: Reg, base: Reg, disp: int = 0) -> bytes:
    """mov dst, [base + disp] — REX.W 8B /r."""
    modrm, extra = _mem_modrm(base, disp, dst)
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0,
               b=1 if base.value >= 8 else 0)
    return bytes([rex, 0x8B, modrm]) + extra


def encode_mov_r32_rm32(dst: Reg, base: Reg, disp: int = 0) -> bytes:
    """mov dst32, [base + disp] — 8B /r with NO REX.W, so it zero-extends.

    The unsigned 4-byte load of the pointer value model (`Pointer[UInt32]`,
    `Pointer[SIMDSize]`).  The REX.W form of the same opcode is the 8-byte load,
    which over-reads a 4-byte pointee by four — the same hazard the arm64 side
    had with `LDR Xt` for `LDR Wt`.  Verified against clang: `unsigned int *p;
    return *p;` compiles to `8b 07  movl (%rdi), %eax`.
    """
    modrm, extra = _mem_modrm(base, disp, dst)
    rex = _rex(r=1 if dst.value >= 8 else 0, b=1 if base.value >= 8 else 0)
    return bytes([rex, 0x8B, modrm]) + extra


def encode_movzx_r64_rm8(dst: Reg, base: Reg, disp: int = 0) -> bytes:
    """movzx dst, [base + disp] — 0F B6 /r, a byte zero-extended to a qword.

    The unsigned 1-byte load of the pointer value model (`Pointer[UInt8]`,
    `Pointer[Byte]`).  No REX.W: the destination is written as a 32-bit
    register, which zero-extends, and a formal value is one 64-bit word.
    Verified against clang: `movzbl (%rdi), %eax` = `0f b6 07`.
    """
    modrm, extra = _mem_modrm(base, disp, dst)
    rex = _rex(r=1 if dst.value >= 8 else 0, b=1 if base.value >= 8 else 0)
    return bytes([rex, 0x0F, 0xB6, modrm]) + extra


def encode_movsx_r64_rm8(dst: Reg, base: Reg, disp: int = 0) -> bytes:
    """movsx dst, [base + disp] — REX.W 0F BE /r, a signed byte to a qword.

    REX.W is what distinguishes this from the unsigned byte load: without it
    the destination is 32 bits and `Int8(-1)` would read back as 255.  Verified
    against clang: `movsbq (%rdi), %rax` = `48 0f be 07`.
    """
    modrm, extra = _mem_modrm(base, disp, dst)
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0, b=1 if base.value >= 8 else 0)
    return bytes([rex, 0x0F, 0xBE, modrm]) + extra


def encode_movzx_r64_rm16(dst: Reg, base: Reg, disp: int = 0) -> bytes:
    """movzx dst, [base + disp] — 0F B7 /r, a halfword zero-extended to a qword.

    Verified against clang: `movzwl (%rdi), %eax` = `0f b7 07`.
    """
    modrm, extra = _mem_modrm(base, disp, dst)
    rex = _rex(r=1 if dst.value >= 8 else 0, b=1 if base.value >= 8 else 0)
    return bytes([rex, 0x0F, 0xB7, modrm]) + extra


def encode_movsx_r64_rm16(dst: Reg, base: Reg, disp: int = 0) -> bytes:
    """movsx dst, [base + disp] — REX.W 0F BF /r, a signed halfword to a qword.

    Verified against clang: `movswq (%rdi), %rax` = `48 0f bf 07`.
    """
    modrm, extra = _mem_modrm(base, disp, dst)
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0, b=1 if base.value >= 8 else 0)
    return bytes([rex, 0x0F, 0xBF, modrm]) + extra


def encode_movsx_r64_rm32(dst: Reg, base: Reg, disp: int = 0) -> bytes:
    """movsxd dst, [base + disp] — REX.W 63 /r, a signed 32-bit to a qword.

    The signed 4-byte load (`Pointer[Int32]`, `Pointer[c_int]`).  REX.W 63 is
    the memory form of the register-form `encode_movsx_r64_r32` that already
    existed here; the memory form is what a dereference needs.  Verified against
    clang: `movslq (%rdi), %rax` = `48 63 07`.
    """
    modrm, extra = _mem_modrm(base, disp, dst)
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0, b=1 if base.value >= 8 else 0)
    return bytes([rex, 0x63, modrm]) + extra


def encode_mov_rm64_r64(base: Reg, disp: int, src: Reg) -> bytes:
    """mov [base + disp], src — REX.W 89 /r."""
    modrm, extra = _mem_modrm(base, disp, src)
    rex = _rex(w=1, r=1 if src.value >= 8 else 0,
               b=1 if base.value >= 8 else 0)
    return bytes([rex, 0x89, modrm]) + extra


def encode_movabs_r64(reg: Reg, imm: int) -> bytes:
    """`movabs reg, imm64` — load an ABSOLUTE address into a register, 10 bytes.

    This is the correct encoding for the module-global `__DATA` segment, and the
    reason is that `GLOBALS_VM` is a FIXED address rather than a link-time
    relative one. Every other absolute reference in an image — a call target, a
    string literal the compiler chose to put in `__TEXT` — moves with the code
    when the loader slides the image, which is exactly what RIP-relative
    addressing encodes. A segment mapped at a hard-coded address does not move,
    so a RIP-relative reference to one drifts by the slide and points somewhere
    the program never chose.

    Measured, and the failure is worth stating precisely because it does not
    look like an addressing bug: the image loaded with a slide of 0x2105000, so
    RIP-relative code computed `__DATA` at 0x102505000 while the segment was
    mapped at its fixed 0x100400000. The initializer's flag word therefore read
    from an address the program never wrote, happened to be non-zero, and the
    initializer was SKIPPED — leaving each address-valued slot holding the
    link-time pointer it shipped with. The first read of such a global then
    dereferenced a non-relocated address and the process died of SIGSEGV, on
    arm64 code that is byte-for-byte correct.

    The arm64 backend's ADRP/ADD has the same PC-relative shape and the same
    hazard; see `arm64_codegen._global_slot_address`, which materialises the
    address with MOVZ/MOVK instead.

    10 bytes: REX.W(+B), opcode B8+rd, then the full 64-bit immediate. A `mov
    r32, imm32` cannot hold the address, which is the whole reason this opcode
    and not that one."""
    return bytes([_rex(w=1, b=1 if reg.value >= 8 else 0), 0xB8 + (reg.value & 7)]) \
        + struct.pack("<q", imm)


def encode_mov_rip_r64(disp: int, src: Reg) -> bytes:
    """mov [rip + disp], src — a RIP-relative STORE, 6 bytes.

    The counterpart of `encode_lea_r64_rip`, and the reason it exists here
    rather than being spelt at the call site: the module-global initializer
    needs to write a computed address to a computed address, and both operands
    are absolute addresses in another segment. A base register for the store
    would mean materialising the slot address first and keeping it live across
    the second LEA, which costs a register this path does not have spare.

    mod=00 with rm=101 is the RIP-relative form of the r/m field (no SIB byte —
    see `encode_lea_r64_rip`), and the displacement counts from the END of the
    instruction, which is what makes it 6 bytes: REX, opcode, ModRM, disp32."""
    assert -2**31 <= disp < 2**31
    rex = _rex(w=1, r=1 if src.value >= 8 else 0)
    return bytes([rex, 0x89, _modrm(0, src.value & 7, 5)]) \
        + struct.pack("<i", disp)


def encode_mov_rm8_r8(base: Reg, disp: int, src: Reg) -> bytes:
    """mov [base + disp], src8 — 88 /r, the low BYTE of `src`.

    The store counterpart of `encode_movzx_r64_r8`, and it exists because the
    64-bit form was the only one: a one-byte element written through
    `encode_mov_rm64_r64` overwrites the seven bytes after it, which is a
    silent corruption of a `malloc`'d buffer rather than anything that traps.
    No REX.W — the operand is a byte, so the prefix that would say "64-bit" is
    the wrong one; a REX prefix is still needed when either register is r8-r15,
    because that is what extends the register field, and `_rex` emits exactly
    that. Verified against clang: `mov %sil, (%rax)` = `40 88 30`.
    """
    modrm, extra = _mem_modrm(base, disp, src)
    rex = _rex(r=1 if src.value >= 8 else 0,
               b=1 if base.value >= 8 else 0)
    return bytes([rex, 0x88, modrm]) + extra


def encode_mov_r32_r32(dst: Reg, src: Reg) -> bytes:
    """mov dst32, src32 (zero-extends into the full 64-bit register)."""
    rex = _rex(r=1 if src.value >= 8 else 0, b=1 if dst.value >= 8 else 0)
    enc = []
    if rex != 0x40:
        enc.append(rex)
    enc.append(0x89)
    enc.append(_modrm(3, src.value & 7, dst.value & 7))
    return bytes(enc)


def encode_movsx_r64_r32(dst: Reg, src: Reg) -> bytes:
    """movsxd dst, src32 — sign-extend 32 -> 64."""
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0,
               b=1 if src.value >= 8 else 0)
    return bytes([rex, 0x63, _modrm(3, dst.value & 7, src.value & 7)])


def encode_movzx_r64_r8(dst: Reg, src: Reg) -> bytes:
    """movzx dst, src8 — zero-extend byte to qword."""
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0,
               b=1 if src.value >= 8 else 0)
    return bytes([rex, 0x0F, 0xB6, _modrm(3, dst.value & 7, src.value & 7)])


def encode_movsx_r64_r8(dst: Reg, src: Reg) -> bytes:
    """movsx dst, src8 — sign-extend byte to qword."""
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0,
               b=1 if src.value >= 8 else 0)
    return bytes([rex, 0x0F, 0xBE, _modrm(3, dst.value & 7, src.value & 7)])


def encode_movzx_r64_r16(dst: Reg, src: Reg) -> bytes:
    """movzx dst, src16 — zero-extend word to qword."""
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0,
               b=1 if src.value >= 8 else 0)
    return bytes([rex, 0x0F, 0xB7, _modrm(3, dst.value & 7, src.value & 7)])


def encode_movsx_r64_r16(dst: Reg, src: Reg) -> bytes:
    """movsx dst, src16 — sign-extend word to qword."""
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0,
               b=1 if src.value >= 8 else 0)
    return bytes([rex, 0x0F, 0xBF, _modrm(3, dst.value & 7, src.value & 7)])


# ── ALU: reg/reg ─────────────────────────────────────────────────────

def _alu_rr(opcode: int, dst: Reg, src: Reg) -> bytes:
    """`opcode /r` in the r/m←reg direction: `dst = dst <op> src`."""
    rex = _rex(w=1, r=1 if src.value >= 8 else 0,
               b=1 if dst.value >= 8 else 0)
    return bytes([rex, opcode, _modrm(3, src.value & 7, dst.value & 7)])


def encode_add_r64_r64(dst: Reg, src: Reg) -> bytes:
    return _alu_rr(0x01, dst, src)


def encode_or_r64_r64(dst: Reg, src: Reg) -> bytes:
    return _alu_rr(0x09, dst, src)


def encode_and_r64_r64(dst: Reg, src: Reg) -> bytes:
    return _alu_rr(0x21, dst, src)


def encode_sub_r64_r64(dst: Reg, src: Reg) -> bytes:
    """sub dst, src  (dst -= src)"""
    return _alu_rr(0x29, dst, src)


def encode_xor_r64_r64(dst: Reg, src: Reg) -> bytes:
    """xor dst, src  (dst ^= src)"""
    return _alu_rr(0x31, dst, src)


def encode_cmp_r64_r64(r1: Reg, r2: Reg) -> bytes:
    """cmp r1, r2  (computes r1 - r2, sets flags)"""
    return _alu_rr(0x39, r1, r2)


def encode_test_r64_r64(r1: Reg, r2: Reg) -> bytes:
    """test r1, r2  (AND without keeping the result)"""
    return _alu_rr(0x85, r1, r2)


def encode_imul_r64_r64(dst: Reg, src: Reg) -> bytes:
    """imul dst, src (dst *= src)"""
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0,
               b=1 if src.value >= 8 else 0)
    return bytes([rex, 0x0F, 0xAF, _modrm(3, dst.value & 7, src.value & 7)])


def encode_imul_r64_r64_imm(dst: Reg, src: Reg, imm: int) -> bytes:
    """imul dst, src, imm8 — REX.W 6B /r ib, a signed 8-bit immediate.

    The three-operand form, and it exists for a pointer subscript's element
    scale: `p[i]` on a `Pointer[Int32]` is `p + i*4`, and the immediate is the
    pointee's width. `imul r, r, imm` is signed on both operands, which is what
    a negative index wants — a C subscript moves the address backwards for one.

    Opcode `6B` and not `69`: `69` is the imm32 form, and using it with a one-byte
    scale reads the following THREE instructions as the immediate. That is not a
    theoretical mistake — it is what this encoder emitted first, and
    `p[0]` on a `Pointer[Int32]` then multiplied the index by 0xD8014C04 (the
    imm32 `04` plus the next twelve bytes of the function) and dereferenced the
    result: SIGSEGV, on an image whose own disassembly agreed with the wrong
    reading. Byte-for-byte against clang's assembler:
    `imulq $4, %rax, %rcx` = `48 6b c8 04`.
    """
    assert -128 <= imm <= 127, f"imul immediate out of imm8 range: {imm}"
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0,
               b=1 if src.value >= 8 else 0)
    return bytes([rex, 0x6B, _modrm(3, dst.value & 7, src.value & 7),
                  imm & 0xFF])


# ── ALU: reg/imm32 ───────────────────────────────────────────────────
#
# Group 1 (0x81) selects the operation with the ModRM reg field:
# /0 ADD, /1 OR, /4 AND, /5 SUB, /6 XOR, /7 CMP.

def encode_add_r64_imm32(reg: Reg, imm: int) -> bytes:
    return _alu_digit(0x81, 0, reg, imm)


def encode_or_r64_imm32(reg: Reg, imm: int) -> bytes:
    return _alu_digit(0x81, 1, reg, imm)


def encode_and_r64_imm32(reg: Reg, imm: int) -> bytes:
    return _alu_digit(0x81, 4, reg, imm)


def encode_sub_r64_imm32(reg: Reg, imm: int) -> bytes:
    return _alu_digit(0x81, 5, reg, imm)


def encode_xor_r64_imm32(reg: Reg, imm: int) -> bytes:
    return _alu_digit(0x81, 6, reg, imm)


def encode_cmp_r64_imm32(reg: Reg, imm: int) -> bytes:
    return _alu_digit(0x81, 7, reg, imm)


def _alu_digit(opcode: int, digit: int, reg: Reg, imm: int) -> bytes:
    assert -2**31 <= imm < 2**31
    rex = _rex(w=1, b=1 if reg.value >= 8 else 0)
    enc = [rex, opcode, _modrm(3, digit, reg.value & 7)]
    enc.extend(struct.pack("<i", imm))
    return bytes(enc)


def encode_add_r64_imm8(reg: Reg, imm: int) -> bytes:
    assert -128 <= imm <= 127
    rex = _rex(w=1, b=1 if reg.value >= 8 else 0)
    return bytes([rex, 0x83, _modrm(3, 0, reg.value & 7), imm & 0xFF])


def encode_sub_r64_imm8(reg: Reg, imm: int) -> bytes:
    assert -128 <= imm <= 127
    rex = _rex(w=1, b=1 if reg.value >= 8 else 0)
    return bytes([rex, 0x83, _modrm(3, 5, reg.value & 7), imm & 0xFF])


def encode_and_r64_imm8(reg: Reg, imm: int) -> bytes:
    assert -128 <= imm <= 127
    rex = _rex(w=1, b=1 if reg.value >= 8 else 0)
    return bytes([rex, 0x83, _modrm(3, 4, reg.value & 7), imm & 0xFF])


def encode_cmp_r64_imm8(reg: Reg, imm: int) -> bytes:
    """cmp reg, imm8 — sets flags without keeping the result."""
    assert -128 <= imm <= 127
    rex = _rex(w=1, b=1 if reg.value >= 8 else 0)
    return bytes([rex, 0x83, _modrm(3, 7, reg.value & 7), imm & 0xFF])


# ── unary / multiply-divide ──────────────────────────────────────────

def _group3(digit: int, reg: Reg) -> bytes:
    """REX.W F7 /digit — the sign/zero/test/multiply/divide family."""
    rex = _rex(w=1, b=1 if reg.value >= 8 else 0)
    return bytes([rex, 0xF7, _modrm(3, digit, reg.value & 7)])


def encode_neg_r64(reg: Reg) -> bytes:
    """neg reg  (two's complement negation)"""
    return _group3(3, reg)


def encode_not_r64(reg: Reg) -> bytes:
    """not reg  (bitwise complement)"""
    return _group3(2, reg)


def encode_mul_r64(reg: Reg) -> bytes:
    """mul reg  — RDX:RAX = RAX * reg"""
    return _group3(4, reg)


def encode_imul_r64_1op(reg: Reg) -> bytes:
    """imul reg  — RDX:RAX = RAX * reg, signed"""
    return _group3(5, reg)


def encode_div_r64(reg: Reg) -> bytes:
    """div reg  — RDX:RAX / reg, unsigned"""
    return _group3(6, reg)


def encode_idiv_r64(reg: Reg) -> bytes:
    """idiv reg — RDX:RAX / reg, signed"""
    return _group3(7, reg)


def encode_cqo() -> bytes:
    """cqo — sign-extend RAX into RDX:RAX before a signed idiv."""
    return bytes([_rex(w=1), 0x99])


def encode_xor_edx_edx() -> bytes:
    """xor edx, edx — zero RDD:RAX before an unsigned div."""
    return bytes([0x31, _modrm(3, Reg.RDX.value, Reg.RDX.value)])


# ── shifts ───────────────────────────────────────────────────────────

def encode_shift_r64_imm8(op: str, reg: Reg, imm: int) -> bytes:
    """shl/shr/sar reg, imm8 — C1 /4 (or /5, /7) ib."""
    assert 0 <= imm <= 255
    digit = {"<<": 4, ">>": 5, ">>signed": 7}.get(op)
    if digit is None:
        raise ValueError(f"unsupported shift {op!r}")
    rex = _rex(w=1, b=1 if reg.value >= 8 else 0)
    return bytes([rex, 0xC1, _modrm(3, digit, reg.value & 7), imm & 0xFF])


def encode_shift_r64_cl(op: str, reg: Reg) -> bytes:
    """shl/shr/sar reg, cl — D3 /4 (or /5, /7)."""
    digit = {"<<": 4, ">>": 5, ">>signed": 7}.get(op)
    if digit is None:
        raise ValueError(f"unsupported shift {op!r}")
    rex = _rex(w=1, b=1 if reg.value >= 8 else 0)
    return bytes([rex, 0xD3, _modrm(3, digit, reg.value & 7)])


# ── lea ──────────────────────────────────────────────────────────────

def encode_lea_r64_rm64(dst: Reg, base: Reg, disp: int) -> bytes:
    """lea dst, [base + disp] — address arithmetic, no memory access."""
    modrm, extra = _mem_modrm(base, disp, dst)
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0,
               b=1 if base.value >= 8 else 0)
    return bytes([rex, 0x8D, modrm]) + extra


def encode_lea_r64_rip(dst: Reg, disp: int) -> bytes:
    """lea dst, [rip + disp] — RIP-relative address materialization.

    7 bytes: REX.W 8D /r with mod=00 and rm=101, which is the encoding that
    means "the displacement is relative to the END of this instruction" and
    is how a string literal's address reaches a register.

    There is NO SIB byte here: mod=00/rm=101 is the RIP-relative form of the
    r/m field, not a request for one. (Emitting one anyway makes the
    instruction 8 bytes, which shifts the displacement field a byte later
    than every back-patch expects and produces a plausible-looking wrong
    address.) The displacement is a placeholder the assembler's `rip` reloc
    replaces once the data's label is known."""
    assert -2**31 <= disp < 2**31
    rex = _rex(w=1, r=1 if dst.value >= 8 else 0)
    return bytes([rex, 0x8D, _modrm(0, dst.value & 7, 5)]) \
        + struct.pack("<i", disp)


# ── setcc ────────────────────────────────────────────────────────────

def _setcc(reg: Reg, cc: int) -> bytes:
    """REX 0F 90+cc /0 — set byte reg to the condition code's boolean value."""
    enc = [0x0F, 0x90 + cc]
    if reg.value >= 8:
        enc.insert(0, _rex(b=1))
    enc.append(_modrm(3, 0, reg.value & 7))
    return bytes(enc)


def encode_sete(reg: Reg) -> bytes:
    """sete r/m8  (set byte if equal, i.e. ZF=1)"""
    return _setcc(reg, COND_E)


def encode_setne(reg: Reg) -> bytes:
    """setne r/m8  (set byte if not equal, i.e. ZF=0)"""
    return _setcc(reg, COND_NE)


def encode_setl(reg: Reg) -> bytes:
    """setl r/m8  (set byte if signed less, i.e. SF!=OF)"""
    return _setcc(reg, COND_L)


def encode_setle(reg: Reg) -> bytes:
    """setle r/m8  (set byte if signed less-or-equal)"""
    return _setcc(reg, COND_LE)


def encode_setg(reg: Reg) -> bytes:
    """setg r/m8  (set byte if signed greater)"""
    return _setcc(reg, COND_G)


def encode_setge(reg: Reg) -> bytes:
    """setge r/m8  (set byte if signed greater-or-equal, i.e. SF=OF)"""
    return _setcc(reg, COND_GE)


def encode_setb(reg: Reg) -> bytes:
    """setb r/m8  (set byte if unsigned below)"""
    return _setcc(reg, COND_B)


def encode_setbe(reg: Reg) -> bytes:
    """setbe r/m8 (set byte if unsigned below-or-equal)"""
    return _setcc(reg, COND_BE)


def encode_seta(reg: Reg) -> bytes:
    """seta r/m8  (set byte if unsigned above)"""
    return _setcc(reg, COND_A)


def encode_setae(reg: Reg) -> bytes:
    """setae r/m8 (set byte if unsigned above-or-equal)"""
    return _setcc(reg, COND_AE)


# ── branches ─────────────────────────────────────────────────────────

def _jcc_rel8(cc: int, offset: int) -> bytes:
    assert -128 <= offset <= 127
    return bytes([0x70 + cc, offset & 0xFF])


def _jcc_rel32(cc: int, offset: int) -> bytes:
    assert -2**31 <= offset < 2**31
    return bytes([0x0F, 0x80 + cc]) + struct.pack("<i", offset)


def encode_je_rel8(offset: int) -> bytes:
    return _jcc_rel8(COND_E, offset)


def encode_jne_rel8(offset: int) -> bytes:
    return _jcc_rel8(COND_NE, offset)


def encode_jcc_rel8(cc: int, offset: int) -> bytes:
    return _jcc_rel8(cc, offset)


def encode_jcc_rel32(cc: int, offset: int) -> bytes:
    return _jcc_rel32(cc, offset)


def encode_jmp_rel8(offset: int) -> bytes:
    assert -128 <= offset <= 127
    return bytes([0xEB, offset & 0xFF])


def encode_jmp_rel32(offset: int) -> bytes:
    assert -2**31 <= offset < 2**31
    return bytes([0xE9]) + struct.pack("<i", offset)


def encode_call_rel32(offset: int) -> bytes:
    assert -2**31 <= offset < 2**31
    return bytes([0xE8]) + struct.pack("<i", offset)


def encode_call_rm64(offset: int) -> bytes:
    """call [rip + offset] — indirect call through memory at RIP-relative address"""
    assert -2**31 <= offset < 2**31
    # "<I", not "<i": the low 32 bits of a NEGATIVE offset do not fit a signed
    # field, and the bytes are the same either way. ("<i" raised struct.error
    # for any offset < 0, so a backwards RIP-relative call — legal, and what a
    # GOT placed before the text produces — could not be encoded at all.)
    return bytes([0xFF, 0x15]) + struct.pack("<I", offset & 0xFFFFFFFF)


def encode_jmp_rm64(offset: int) -> bytes:
    """jmp [rip + offset] — indirect jump through memory at RIP-relative address"""
    assert -2**31 <= offset < 2**31
    return bytes([0xFF, 0x25]) + struct.pack("<I", offset & 0xFFFFFFFF)


def encode_jne_rel32(offset: int) -> bytes:
    """`jne rel32` — branch if the ZERO flag is clear.

    NOT `jne [rip + offset]`. That was the original form here, and it was wrong
    in a way that read as a working instruction: `jcc rel32` is encoded
    `0F 8x cd` with NO ModRM byte, because the condition code IS the low byte
    of the opcode and there is no register operand to encode. Emitting a ModRM
    anyway puts one extra byte between the opcode and the displacement, so the
    CPU — and every disassembler — reads the first byte of the intended
    displacement as a ModRM and the branch lands `offset` bytes somewhere else.
    Measured: the lazy-initializer's "already initialised, skip the body"
    branch jumped 0xE15 bytes past the end of the image, and the x86-64
    backend SIGBUSed on every program with a module global while the arm64
    backend, whose equivalent CBNZ takes no operands either, ran the same source
    correctly.

    What made it survive inspection is that the emitted bytes are still a
    plausible `0f 85` prefix — a wrong-but-valid prefix reads as a branch, so
    the only symptom is a branch to an address nobody chose.

    6 bytes: `0F 85 disp32`, displacement relative to the END of the
    instruction. `reg` is gone with the ModRM; the caller branches on the flags
    that `cmp`/`test` left behind, so there is nothing else to name here."""
    assert -2**31 <= offset < 2**31
    return bytes([0x0F, 0x85]) + struct.pack("<i", offset)


# ── assembler ────────────────────────────────────────────────────────

class Assembler:
    """x86-64 assembler with label and relocation support.

    `org` sets the base virtual address; `label` records an absolute address;
    `emit_label_rel8`/`emit_label_rel32` record a branch fixup whose operand
    starts at the current position (optionally biased by `here_offset`, which
    is how a call site back-patches the rel32 it just emitted). `resolve`
    back-patches every fixup once all labels are known.
    """

    def __init__(self):
        self.sections: dict[str, bytearray] = {"text": bytearray()}
        self.labels: dict[str, int] = {}
        self.relocs: list[tuple[str, str, int]] = []
        self.extern_refs: list[tuple[str, int, int, str]] = []
        """(sym_name, abs_pos_of_instruction, instr_len, instr_kind) where
        instr_kind is 'call'."""
        self._org = 0

    def org(self, addr: int):
        self._org = addr

    def label(self, name: str):
        """Bind `name` to the current address — once.

        A SECOND binding of the same name is an error rather than a rebinding.
        Every branch to a label is patched in `resolve` out of this table, so a
        later definition silently retargets every earlier reference to it, and
        what that builds is a branch into the middle of a different instruction
        sequence. Nothing downstream can see it: the image is well formed, the
        run exits 0, and the answer is simply a different number.

        That is not hypothetical. Two label names in `x86_64_codegen.py` were
        built without the per-site counter every other one carries — the three
        bound-clamp labels of `_emit_slice_parts`, named after the register
        alone — so a second slice in one function rebound the first slice's
        `jge` and `xs[1:3]` followed by `xs[2:6]` answered 14 for a sum of 23,
        or died
        (fixed 2026-10-03 in 68671a62). The
        `_emit_range_list` labels collided the same way before that
        (`bugs/FORMAL_x86_64_end_to_end_proof.md`, "Nested comprehensions"). So
        a name is required to be unique per emission site, and this is where
        that is enforced rather than remembered; `arm64.Assembler.label` carries
        the same check for the same reason.
        """
        if name in self.labels:
            raise CodegenError(
                f"internal: label {name!r} is defined twice, at 0x"
                f"{self.labels[name]:x} and at 0x"
                f"{self._org + len(self.sections['text']):x}. Branch targets "
                "are patched from this table, so every earlier branch to it now "
                "lands in the middle of this second block. A label name must "
                "carry a per-site counter (see every label in "
                "formal/x86_64_codegen.py, e.g. assert{aid} / sl{sid}).")
        self.labels[name] = self._org + len(self.sections["text"])

    def emit(self, data: bytes):
        self.sections["text"].extend(data)

    def emit_label_rel8(self, label_name: str, here_offset: int = 0):
        """Record a rel8 branch fixup whose displacement byte is at the
        current position (biased by `here_offset`).

        The SAME convention as `emit_label_rel32` below, and it is stated here
        because `resolve` does not enforce it: the recorded address is the
        displacement BYTE, not the instruction, and a rel8 branch is two bytes
        long, so a caller back-patching the `jcc rel8` it just emitted passes
        `here_offset=-1`. Passing the rel32 form's `-4` writes four bytes too
        early, which overwrites the opcode of the branch and the two bytes
        before it — a silently misdecoded instruction stream rather than a
        rejected encoding. (Measured while landing the stack-floor guard, which
        is the first caller of this method.)"""
        self.relocs.append(
            ("j8", label_name,
             self._org + len(self.sections["text"]) + here_offset))

    def emit_label_rel32(self, label_name: str, here_offset: int = 0):
        """Record a rel32 branch fixup whose displacement field is at the
        current position (biased by `here_offset`).

        The convention all three of these share, and which `resolve` depends
        on, is that the recorded address is the start of the DISPLACEMENT, not
        the start of the instruction: x86 displacements are relative to the
        end of the instruction, so a 2-byte jcc is recorded with
        `here_offset=-1` and a 5-byte call/jmp with `here_offset=-4`."""
        self.relocs.append(
            ("j32", label_name,
             self._org + len(self.sections["text"]) + here_offset))

    def emit_label_rip(self, label_name: str, here_offset: int = 0):
        """Record a RIP-relative displacement fixup (a `lea` of a data
        address). Same convention: `here_offset` locates the disp32 field,
        which sits 3 bytes into the 7-byte encoding."""
        self.relocs.append(
            ("rip", label_name,
             self._org + len(self.sections["text"]) + here_offset))


    def emit_extern_call(self, sym_name: str):
        """Emit `call rel32 0` (5 bytes) and record it for stub patching.

        The call targets a linker-provided stub that jumps through a GOT slot
        the loader binds; `resolve_extern` back-patches the rel32 with the
        stub's address once the binary layout is known. This is the Mach-O
        extern path, where the image carries a __TEXT,__stubs section."""
        pos = self._org + len(self.sections["text"])
        self.sections["text"].extend(encode_call_rel32(0))
        self.extern_refs.append((sym_name, pos, 5, "call"))

    def emit_extern_call_got(self, sym_name: str):
        """Emit `call [rip+disp32]` (6 bytes) and record it for GOT patching.

        The indirect form needs no stub section at all: the dynamic linker
        fills the GOT slot (R_X86_64_GLOB_DAT) and the call goes straight
        through it. This is the ELF extern path — see formal/elf.py, which
        emits no __text,__stubs equivalent."""
        pos = self._org + len(self.sections["text"])
        self.sections["text"].extend(encode_call_rm64(0))
        self.extern_refs.append((sym_name, pos, 6, "call_got"))

    def resolve(self):
        # Report EVERY undefined label, not just the first: a function body
        # that forgets one `label()` per branch is the common case, and
        # failing one label per build turns a one-line omission into a long
        # bisect.
        missing = sorted({label for _kind, label, _pos in self.relocs
                          if label not in self.labels})
        if missing:
            raise ValueError(
                f"Undefined label(s): {', '.join(missing)}")
        for kind, label, pos in self.relocs:
            target = self.labels[label]
            idx = pos - self._org
            if kind == "j8":
                # rel8 is measured from the END of the 2-byte instruction.
                offset = target - (pos + 1)
                assert -128 <= offset <= 127, f"j8 offset out of range: {offset}"
                self.sections["text"][idx] = offset & 0xFF
            elif kind == "j32":
                # rel32 is measured from the END of the 5-byte instruction.
                offset = target - (pos + 4)
                assert -2**31 <= offset < 2**31, \
                    f"j32 offset out of range: {offset}"
                self.sections["text"][idx:idx + 4] = struct.pack(
                    "<i", offset)
            elif kind == "rip":
                # A RIP-relative displacement runs from the end of the 7-byte
                # LEA that carries it.
                offset = target - (pos + 4)
                assert -2**31 <= offset < 2**31, \
                    f"rip-relative offset out of range: {offset}"
                self.sections["text"][idx:idx + 4] = struct.pack(
                    "<i", offset)
        self.relocs.clear()

    def resolve_extern(self, target_addrs: dict[str, int]):
        """Patch extern call sites to reach a linker-provided target.

        `call` (Mach-O path): re-emitted as a `call rel32` to the address in
        `target_addrs`, which is the symbol's __TEXT,__stubs entry — a
        trampoline that jumps through a loader-bound GOT slot. This mirrors
        the arm64 assembler's contract, and like it the WHOLE instruction is
        rewritten rather than a field inside it patched: the two differ in
        length depending on the target, and the recorded position is the
        instruction's start, so patching a fixed field at a fixed offset
        would eventually write the opcode.

        `call_got` (ELF path): re-emitted as a `call [rip+disp32]` through the
        GOT slot, since the ELF image has no stub section and the call is
        indirect through the slot the dynamic linker fills."""
        for sym_name, pos, instr_len, kind in self.extern_refs:
            if sym_name not in target_addrs:
                raise ValueError(f"Undefined external symbol: {sym_name}")
            target = target_addrs[sym_name]
            idx = pos - self._org
            if kind == "call_got":
                # The displacement is measured from the END of the 6-byte
                # instruction.
                disp = target - (pos + instr_len)
                assert -2**31 <= disp < 2**31, \
                    f"extern RIP-relative offset out of range: {disp}"
                self.sections["text"][idx:idx + instr_len] = \
                    encode_call_rm64(disp)
                continue
            offset = target - (pos + instr_len)
            assert -2**31 <= offset < 2**31, \
                f"extern rel32 out of range: {offset}"
            self.sections["text"][idx:idx + instr_len] = \
                encode_call_rel32(offset)

