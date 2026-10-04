#!/usr/bin/env python3
"""ARM64 (AArch64) instruction encoder and assembler.

All ARM64 instructions are 4 bytes (32 bits), little-endian encoded.
"""

import struct

from formal.model import CodegenError

# ARM64 register numbers
# X0-X30: general purpose 64-bit registers
# XZR/WZR: zero register (31)
# SP: stack pointer (31, but accessed specially)
# PC: program counter (32)
#
# Naming convention:
#   - Xd, Xn, Xm, Rt, Rs: register operands
#   - imm, imm12, imm16: immediate values
#   - cond: condition code for CSET (eq, ne, cs, cc, mi, pl, vs, vc, hi, ls, ge, lt, gt, le)


def encode_adrp(xd: int, page_offset: int) -> bytes:
    """ADRP Xd, #page. Loads the page base of PC-relative page.
    page_offset is a signed multiple of 0x1000.
    Encoding: 1 immlo(2) 10000 immhi(19) Rd
    """
    assert 0 <= xd <= 30
    assert page_offset % 0x1000 == 0
    page = page_offset // 0x1000
    assert -2**20 <= page < 2**20, page
    page &= 0x1fffff
    immlo = page & 0x3
    immhi = (page >> 2) & 0x7ffff
    insn = 0x90000000 | (immlo << 29) | (immhi << 5) | xd
    return struct.pack('<I', insn)


def encode_ldr_xt_xn_imm(xt: int, xn: int, imm: int) -> bytes:
    """LDR Xt, [Xn, #imm]. Unsigned immediate offset load, 64-bit.
    imm must be a multiple of 8.
    Encoding: 1111100101 imm12 Rn Rt (imm12 = imm/8)
    """
    assert 0 <= xt <= 30
    assert 0 <= xn <= 31
    assert imm % 8 == 0
    imm12 = imm // 8
    assert 0 <= imm12 < 0x1000
    insn = 0xf9400000 | (imm12 << 10) | (xn << 5) | xt
    return struct.pack('<I', insn)


def encode_ldr_xt_xn_xm(xt: int, xn: int, xm: int) -> bytes:
    """LDR Xt, [Xn, Xm] — unsigned offset REGISTER form, 64-bit, no shift.

    The escape from `encode_ldr_xt_xn_imm`'s 12-bit scaled offset, which reaches
    only 32760 bytes. A list blob's element `i` lives at byte `8*(i+1)`, so
    element 4095 is the first one the immediate form cannot name, and a list
    literal that long used to die inside the encoder's own `assert` rather than
    in a diagnostic. Here the offset is a register, so the reachable distance is
    the whole 64-bit address space and the limit becomes the frame size, which
    is a limit the build can state.

    Encoding: 1111100100 10 1 Rm 011 0 10 Rn Rt (0xF8606800 base). Verified
    against clang -target aarch64-apple-darwin, `otool -s __TEXT __text`:
    ldr x0,[x9,x10] = f86a6920, ldr x0,[x9,x15] = f86f6920,
    ldr x10,[x9,x0] = f860692a.
    """
    assert 0 <= xt <= 30
    assert 0 <= xn <= 31
    assert 0 <= xm <= 31
    insn = 0xF8606800 | (xm << 16) | (xn << 5) | xt
    return struct.pack('<I', insn)


def encode_str_xt_xn_xm(xt: int, xn: int, xm: int) -> bytes:
    """STR Xt, [Xn, Xm] — unsigned offset REGISTER form, 64-bit, no shift.

    The store-side twin of `encode_ldr_xt_xn_xm`, and for the same reason: this
    is the form a blob element past 32760 bytes has to use, and the list
    literal's element loop is where that store happens.

    Encoding: 1111100100 00 1 Rm 011 0 10 Rn Rt (0xF8206800 base). Verified
    against clang -target aarch64-apple-darwin, `otool -s __TEXT __text`:
    str x0,[x9,x10] = f82a6920, str x0,[x9,x15] = f82f6920.
    """
    assert 0 <= xt <= 30
    assert 0 <= xn <= 31
    assert 0 <= xm <= 31
    insn = 0xF8206800 | (xm << 16) | (xn << 5) | xt
    return struct.pack('<I', insn)


def encode_ldrb_wd_wn(wd: int, wn: int, imm: int = 0) -> bytes:
    """LDRB Wd, [Xn, #imm]. Byte load, zero-extends into Xd.

    Encoding: 0011100101 imm12 Rn Rt (0x39400000 base); imm is a byte
    offset (not scaled). Verified against `as`: ldrb w0,[x9] = 20014039.
    """
    assert 0 <= wd <= 30
    assert 0 <= wn <= 31
    assert 0 <= imm < 0x1000
    insn = 0x39400000 | (imm << 10) | (wn << 5) | wd
    return struct.pack('<I', insn)


def encode_strb_wd_wn(wd: int, wn: int, imm: int = 0) -> bytes:
    """STRB Wd, [Xn, #imm]. Byte store from Wd.

    Encoding: 0011100100 imm12 Rn Rt (0x39000000 base); imm is a byte
    offset. Verified against `as`: strb w0,[x9] = 20010039.
    """
    assert 0 <= wd <= 30
    assert 0 <= wn <= 31
    assert 0 <= imm < 0x1000
    insn = 0x39000000 | (imm << 10) | (wn << 5) | wd
    return struct.pack('<I', insn)


def encode_str_wt_wn_imm(wt: int, wn: int, imm: int = 0) -> bytes:
    """STR Wt, [Xn, #imm] — store 32 bits.

    The store counterpart of `encode_ldr_wt_wn_imm`, and it exists because the
    pointer value model's STORE needs one instruction per pointee width: the set
    had the byte store (`encode_strb_wd_wn`), the halfword store
    (`encode_strh_wt_wn_imm`) and the full one (`encode_str_xt_xn_imm`), and the
    4-byte case had no encoder, so a `Pointer[Int32]`'s store would have had to
    be either an 8-byte store (which overwrites four bytes the program never
    wrote — silent corruption of a `malloc`'d buffer) or an 8-byte store
    truncated afterwards, which is the same store plus a wasted instruction.

    Writing Wt rather than Xt is what keeps the store 32 bits wide; the upper
    half of Xt is not written, so the four bytes after the pointee are whatever
    they were.  Verified against `as`: `str w0, [x0]` = 0xb9000000.
    """
    assert 0 <= wt <= 30 and 0 <= wn <= 31
    assert 0 <= imm <= 16380 and imm % 4 == 0
    return struct.pack('<I', 0xB9000000 | ((imm >> 2) << 10) | (wn << 5) | wt)


def encode_br_xn(xn: int) -> bytes:
    """BR Xn. Unconditional branch to register.
    Encoding: 11010110000 11111 000000 00000 Rn
    """
    assert 0 <= xn <= 30
    insn = 0xd61f0000 | (xn << 5)
    return struct.pack('<I', insn)


def encode_blr_xn(xn: int) -> bytes:
    """BLR Xn. Branch-with-link to register (indirect call).
    Encoding: 11010110001 11111 000000 Rn 00000 = 0xd63f0000 | (Rn << 5)
    """
    assert 0 <= xn <= 30
    insn = 0xd63f0000 | (xn << 5)
    return struct.pack('<I', insn)


def encode_svc(imm8: int) -> bytes:
    """SVC #imm8. Software interrupt.
    Encoding (matches clang/ld's `svc #0x80` = 0xd4001001):
    0xd4000000 | ((imm8 & 0xffff) << 5) | 0x1
    """
    assert 0 <= imm8 <= 0xff
    insn = 0xd4000000 | ((imm8 & 0xffff) << 5) | 0x1
    return struct.pack('<I', insn)


def encode_movz_xn_imm(xn: int, imm16: int) -> bytes:
    """MOVZ Xn, #imm16. Move zeroing with 16-bit immediate.
    Encoding: 110100 0 0 imm16(16) 00000 Rn
    """
    assert 0 <= xn <= 31
    assert 0 <= imm16 <= 0xffff
    insn = 0xd2800000 | (imm16 << 5) | xn
    return struct.pack('<I', insn)


def encode_ret() -> bytes:
    """RET = BR X30. Encoding: 110101 1 01010 1 11110 0 000000"""
    return struct.pack('<I', 0xd65f03c0)


def encode_mov_zr_xn(xd: int, xn: int) -> bytes:
    """MOV Xd, Xn = ADD Xd, Xn, #0. Full 64-bit register copy.
    Verified: 0x91000000 | (xn << 5) | xd (with Rd=X31 for SP)
    """
    assert 0 <= xd <= 31  # Allow X31 (SP) as destination
    assert 0 <= xn <= 31
    insn = 0x91000000 | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_movz_xd_imm(xd: int, imm16: int) -> bytes:
    """MOVZ Xd/Wd, #imm16. Sets lower 16 bits to imm16, clears upper bits.
    Encoding: 100101 opec 00 00000 imm16 xd (sf/opc choose 32 vs 64-bit)
    """
    assert 0 <= xd <= 30
    assert 0 <= imm16 <= 0xffff
    insn = 0x52800000 | (imm16 << 5) | xd
    return struct.pack('<I', insn)


def encode_movk_xd_imm(xd: int, imm16: int, pos: int) -> bytes:
    """MOVK Xd, #imm16, #pos. Inserts imm16 at bit position pos (0, 16, 32, 48).
    Encoding: 100101 0 HW 00000 imm16 xd
    HW = pos >> 4 (0=low, 1=16-31, 2=32-47, 3=48-63)
    """
    assert 0 <= xd <= 30
    assert 0 <= imm16 <= 0xffff
    assert pos in (0, 16, 32, 48)
    hw = pos >> 4
    insn = 0xf2800000 | (hw << 21) | (imm16 << 5) | xd
    return struct.pack('<I', insn)


def encode_movn_xd_imm(xd: int, imm16: int) -> bytes:
    """MOVN Xd, #imm16. Sets lower 16 bits to ~imm16, clears upper 48 bits.
    Encoding: 100101 0 00 00001 imm16 xd
    """
    assert 0 <= xd <= 30
    assert 0 <= imm16 <= 0xffff
    insn = 0x12800000 | (imm16 << 5) | xd
    return struct.pack('<I', insn)


def encode_add_xd_xn_imm(xd: int, xn: int, imm12: int) -> bytes:
    """ADD Rd, Rn, #imm12. Rd = Rn + imm12.
    Verified: 0x81000000 | (imm12 << 10) | (xn << 5) | xd
    """
    assert 0 <= xd <= 31
    assert 0 <= xn <= 31
    assert 0 <= imm12 <= 0xfff
    insn = 0x91000000 | (imm12 << 10) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_add_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """ADD Rd, Rn, Xm. Rd = Rn + Xm.
    Verified encoding: 0x8b000000 | (xm << 16) | (xn << 5) | xd
    """
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    assert 0 <= xm <= 30
    insn = 0x8b000000 | (xm << 16) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_add_xd_xn_xm_lsl3(xd: int, xn: int, xm: int) -> bytes:
    """ADD Xd, Xn, Xm, LSL #3. Xd = Xn + (Xm << 3).
    Element-address step for int64 list blobs. Verified against `as`:
    add x0, x1, x2, lsl #3 = 8b020c20."""
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    assert 0 <= xm <= 30
    insn = 0x8b000000 | (xm << 16) | (3 << 10) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_add_xd_xn_xm_lsl4(xd: int, xn: int, xm: int) -> bytes:
    """ADD Xd, Xn, Xm, LSL #4. Xd = Xn + (Xm << 4).
    Element-address step for dict pair blobs ([count][k][v]…, 16 bytes
    per pair). Verified against `as`: add x4, x9, x3, lsl #4 = 8b031124."""
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    assert 0 <= xm <= 30
    insn = 0x8b000000 | (xm << 16) | (4 << 10) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_sub_xd_xn_imm(xd: int, xn: int, imm12: int) -> bytes:
    """SUB Rd, Rn, #imm12. Rd = Rn - imm12.
    Immediate offset form (clang-canonical): sub sp, sp, #4032 = 0xd13f03ff.
    Verified: 0xd1000000 | (imm12 << 10) | (xn << 5) | xd
    """
    assert 0 <= xd <= 31
    assert 0 <= xn <= 31
    assert 0 <= imm12 <= 0xfff
    insn = 0xd1000000 | (imm12 << 10) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_sub_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """SUB Rd, Rn, Xm. Rd = Rn - Xm.
    Verified encoding: 0xcb000000 | (xm << 16) | (xn << 5) | xd
    """
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    assert 0 <= xm <= 30
    insn = 0xcb000000 | (xm << 16) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_mul_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """MUL Rd, Rn, Xm. Rd = Rn * Xm (lower 64 bits only).
    Verified encoding: 0x9b007c00 | (xm << 16) | (xn << 5) | xd
    """
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    assert 0 <= xm <= 30
    insn = 0x9b007c00 | (xm << 16) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_neg_xd_xn(xd: int, xn: int) -> bytes:
    """NEG Rd, Rn. Rd = -Rn (two's complement).
    Verified encoding: 0xcb0003e0 | (xn << 16) | xd
    """
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    insn = 0xcb0003e0 | (xn << 16) | xd
    return struct.pack('<I', insn)


def encode_cmp_xn_imm(xn: int, imm12: int) -> bytes:
    """CMP Rn, #imm12. Sets flags based on Rn - imm12 (SUBS XZR, Rn, XZR, #imm12).
    imm12 is bits [20:10], Rn is bits [9:5], Rd = XZR (0x1f).
    Verified: 0xf1000000 | (imm12 << 10) | (xn << 5) | 0x1f
    """
    assert 0 <= xn <= 31
    assert 0 <= imm12 <= 0xfff
    insn = 0xf1000000 | (imm12 << 10) | (xn << 5) | 0x1f
    return struct.pack('<I', insn)


def encode_cmp_xn_xm(xn: int, xm: int) -> bytes:
    """CMP Rn, Xm. Sets flags based on Rn - Xm.
    Verified: 0xeb000000 | (xm << 16) | (xn << 5)
    """
    assert 0 <= xn <= 31
    assert 0 <= xm <= 30
    insn = 0xEB000000 | (xm << 16) | (xn << 5) | 0x1f
    return struct.pack('<I', insn)


def encode_b(offset: int) -> bytes:
    """B #offset. Unconditional branch. offset is in 4-byte units, signed 26-bit.
    Encoding: 000101 imm26
    """
    assert -2**25 <= offset < 2**25
    insn = 0x14000000 | (offset & 0x03ffffff)
    return struct.pack('<I', insn)


def encode_bl(offset: int) -> bytes:
    """BL #offset. Branch with link. Sets LR (X30) to PC+4, then branches.
    Encoding: 100101 imm26
    """
    assert -2**25 <= offset < 2**25
    insn = 0x94000000 | (offset & 0x03ffffff)
    return struct.pack('<I', insn)


def encode_cbz_xn(offset: int, xn: int) -> bytes:
    """CBZ Xn, #offset. Branch if Xn is zero.
    Verified: 0xb4000000 | ((offset // 4) << 5) | xn
    """
    assert 0 <= xn <= 31
    assert -2**18 <= offset < 2**18
    insn = 0xb4000000 | ((offset // 4) << 5) | xn
    return struct.pack('<I', insn)


def encode_cbnz_xn(offset: int, xn: int) -> bytes:
    """CBNZ Xn, #offset. Branch if Xn is non-zero.
    Verified: 0xb5000000 | ((offset // 4) << 5) | xn
    """
    assert 0 <= xn <= 31
    assert -2**18 <= offset < 2**18
    insn = 0xb5000000 | ((offset // 4) << 5) | xn
    return struct.pack('<I', insn)


def encode_stp_sp_pre(rt1: int, rt2: int, b: int = 16) -> bytes:
    """STP Xrt1, Xrt2, [SP, #-b]! — pre-indexed store pair, 16-byte aligned stack ops.

    clang-canonical: `stp x0, x1, [sp, #-16]!` = 0xA9BF07E0.
    imm7 (bits[21:15]) is the signed byte offset in units of 8.
    """
    assert 0 <= rt1 <= 30 and 0 <= rt2 <= 31
    assert b > 0 and b % 8 == 0
    imm7 = (-(b // 8)) & 0x7F
    insn = (0x2A6 << 22) | (imm7 << 15) | (rt2 << 10) | (0x1F << 5) | rt1
    return struct.pack('<I', insn)


def encode_ldp_sp_post(rt1: int, rt2: int, b: int = 16) -> bytes:
    """LDP Xrt1, Xrt2, [SP], #b — post-indexed load pair, 16-byte aligned stack ops.

    clang-canonical: `ldp x0, x1, [sp], #16` = 0xA8C107E0.
    imm7 (bits[21:15]) is the unsigned byte offset in units of 8.
    """
    assert 0 <= rt1 <= 30 and 0 <= rt2 <= 31
    assert b > 0 and b % 8 == 0
    imm7 = (b // 8) & 0x7F
    insn = (0x2A3 << 22) | (imm7 << 15) | (rt2 << 10) | (0x1F << 5) | rt1
    return struct.pack('<I', insn)


def encode_str_xt_xn_imm(xt: int, xn: int, imm: int) -> bytes:
    """STR Xt, [Xn, #imm]. Unsigned immediate offset store, 64-bit, no writeback.

    imm is the byte offset (multiple of 8); encoding field is imm/8.
    Matches encode_ldr_xt_xn_imm's parameter convention.
    """
    assert 0 <= xt <= 30 and 0 <= xn <= 31
    assert imm % 8 == 0
    imm12 = imm // 8
    assert 0 <= imm12 < 0x1000
    insn = 0xF9000000 | (imm12 << 10) | (xn << 5) | xt
    return struct.pack('<I', insn)


def encode_str_xt_sp_imm(xt: int, imm12: int, pre_indexed: bool = True) -> bytes:
    """STR Xt, [SP, #imm]. Unsigned immediate offset store, 64-bit, no writeback.

    imm12 is the byte offset in units of 8. Encoding: 1111100101 imm12 Rn Rt
    """
    assert 0 <= xt <= 30
    assert 0 <= imm12 <= 0xfff
    insn = 0xF9000000 | (imm12 << 10) | (31 << 5) | xt
    return struct.pack('<I', insn)


def encode_ldr_xt_sp_imm(xt: int, imm12: int) -> bytes:
    """LDR Xt, [SP, #imm]. Unsigned immediate offset load, 64-bit, no writeback.

    imm12 is the byte offset in units of 8. Encoding: 1111100101 imm12 Rn Rt
    """
    assert 0 <= xt <= 30
    assert 0 <= imm12 <= 0xfff
    insn = 0xF9400000 | (imm12 << 10) | (31 << 5) | xt
    return struct.pack('<I', insn)


def encode_ldp_xn_xt_sp(xn: int, xt: int, imm12: int) -> bytes:
    """LDP Xt, Xn, [SP], #imm. Loads two 64-bit registers from the stack.
    Encoding: 10110 1 1 00000 1 imm12 Rn Rt Rs
    """
    assert 0 <= xn <= 31
    assert 0 <= xt <= 30
    assert 0 <= imm12 <= 0xfff
    # Encoding: 0xA9400000 | (imm12 << 10) | (xn << 5) | xt
    insn = 0xA9400000 | (imm12 << 10) | (xn << 5) | xt
    return struct.pack('<I', insn)


def encode_cset_wd_cond(xd: int, cond: str) -> bytes:
    """CSET Wd, cond. Sets Wd to 0 or 1 based on condition code.
    Encoding: base 0x9a9f03e0, cond_high at bit 15, field=((cond&7)^1)<<2|1 at bits 14-10
    """
    assert 0 <= xd <= 30
    cond_map = {
        'eq': 0, 'ne': 1, 'cs': 2, 'cc': 3, 'mi': 4, 'pl': 5,
        'vs': 6, 'vc': 7, 'hi': 8, 'ls': 9, 'ge': 10, 'lt': 11,
        'gt': 12, 'le': 13
    }
    if cond not in cond_map:
        raise ValueError(f"Unknown condition: {cond}")
    c = cond_map[cond]
    cond_high = c >> 3
    field = ((c & 7) ^ 1) << 2 | 1
    insn = 0x9a9f03e0 | (cond_high << 15) | (field << 10) | xd
    return struct.pack('<I', insn)


def encode_cset_xd_cond(xd: int, cond: str) -> bytes:
    """CSET Xd, cond. Sets Xd to 0 or 1 based on condition code (64-bit version).
    Encoding: base 0x9a9f03e0, cond_high at bit 15, field=((cond&7)^1)<<2|1 at bits 14-10
    """
    assert 0 <= xd <= 30
    cond_map = {
        'eq': 0, 'ne': 1, 'cs': 2, 'cc': 3, 'mi': 4, 'pl': 5,
        'vs': 6, 'vc': 7, 'hi': 8, 'ls': 9, 'ge': 10, 'lt': 11,
        'gt': 12, 'le': 13
    }
    if cond not in cond_map:
        raise ValueError(f"Unknown condition: {cond}")
    c = cond_map[cond]
    cond_high = c >> 3
    field = ((c & 7) ^ 1) << 2 | 1
    insn = 0x9a9f03e0 | (cond_high << 15) | (field << 10) | xd
    return struct.pack('<I', insn)


def encode_and_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """AND Rd, Rn, Xm. Rd = Rn AND Xm.
    Encoding: 000101 0 0 000000 0 0 Rm Rn Rd (sf=1, op=0, m=0)
    """
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    assert 0 <= xm <= 30
    insn = 0x8A000000 | (xm << 16) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_orr_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """ORR Rd, Rn, Xm. Rd = Rn OR Xm.
    Encoding: 000101 0 0 000000 0 0 Rm Rn Rd (sf=1, op=0, m=0) but different primary opcode
    """
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    assert 0 <= xm <= 30
    insn = 0xAA000000 | (xm << 16) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_orn_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """ORN Rd, Rn, Xm. Rd = ~Rn OR Xm (bitwise NOT then OR).
    Encoding: 0b0 sf=1 opc=01 01010 1 0 Rm imm6 Rn Rd

    The `N` bit (bit 21) is what makes this ORN rather than OR, and the `sf`
    bit (bit 31) is what makes it the 64-bit form. Verified against the
    assembler: `orn x2, xzr, x3` assembles to 0xAA2303E2, and this with
    xd=2, xn=31, xm=3 is 0xAA200000 | (3 << 16) | (31 << 5) | 2. The
    previous constants here had sf=0 and Rm in the wrong field, so it
    emitted a 32-bit AND; nothing called it, which is the only reason that
    went unnoticed."""
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    assert 0 <= xm <= 30
    insn = 0xAA200000 | (xm << 16) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_mvn_xd_xn(xd: int, xn: int) -> bytes:
    """MVN Rd, Rn. Rd = ~Rn (bitwise NOT). The unary `~`.

    MVN is an alias of `ORN Rd, ZR, Rn` — ~Rn OR 0 — so this is `encode_orn`
    with the first source register fixed at 31, and it is spelled as that
    rather than as a second copy of the constant so the two cannot come
    apart. Verified against the assembler: `mvn x0, x1` is 0xAA2103E0, and
    this with xd=0, xn=1 is 0xAA200000 | (31 << 5) | (1 << 5) | 0.

    This is the arm64 half of `~x`; before it existed the arm64 backend had
    no `~` branch at all, so `~` on an integer could only be refused (or, on
    the pre-lexer-fix tree, silently dropped by the tokenizer)."""
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    return encode_orn_xd_xn_xm(xd, 31, xn)


def encode_eor_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """EOR Rd, Rn, Xm. Rd = Rn XOR Xm.
    Encoding: 000101 0 0 000000 0 0 Rm Rn Rd (sf=1, op=0, m=0) but with EOR primary opcode
    """
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    assert 0 <= xm <= 30
    insn = 0xCA000000 | (xm << 16) | (xn << 5) | xd
    return struct.pack('<I', insn)


# Signed extend / zero-truncate immediates, verified against clang (objdump):
#   sxtb w0, w1 = 0x13001c20, sxth w0, w2 = 0x13003c40, sxtw x0, w3 = 0x93407c60
#   and x0, x1, #0xff = 0x92401c20, #0xffff = 0x92403ca4, #0xffffffff = 0x92407ce6

_SXT_BASES = {8: 0x13001c00, 16: 0x13003c00}  # SXTB / SXTH (32-bit result)
_AND_IMM_BASES = {8: 0x92401c00, 16: 0x92403c00, 32: 0x92407c00}


def encode_sxtb_wd_wn(wd: int, wn: int) -> bytes:
    """SXTB Wd, Wn. Sign-extend byte 0 of Wn to 32 bits (zero-extends to 64)."""
    assert 0 <= wd <= 30 and 0 <= wn <= 30
    return struct.pack('<I', _SXT_BASES[8] | (wn << 5) | wd)


def encode_sxth_wd_wn(wd: int, wn: int) -> bytes:
    """SXTH Wd, Wn. Sign-extend halfword 0 of Wn to 32 bits (zero-extends to 64)."""
    assert 0 <= wd <= 30 and 0 <= wn <= 30
    return struct.pack('<I', _SXT_BASES[16] | (wn << 5) | wd)


def encode_sxtw_xd_wn(xd: int, wn: int) -> bytes:
    """SXTW Xd, Wn. Sign-extend Wn to 64 bits."""
    assert 0 <= xd <= 30 and 0 <= wn <= 30
    return struct.pack('<I', 0x93407c00 | (wn << 5) | xd)


def encode_and_xd_xn_imm(xd: int, xn: int, width: int) -> bytes:
    """AND Xd, Xn, #(2^width - 1). Zero-truncate to `width` bits.
    width in (8, 16, 32); 64-bit logical immediate, no rotation."""
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    assert width in _AND_IMM_BASES
    return struct.pack('<I', _AND_IMM_BASES[width] | (xn << 5) | xd)


def encode_sdiv_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """SDIV Xd, Xn, Xm. Signed integer division (trunc toward zero).
    Encoding: 1 0 0 11010110 Rm 000011 Rn Rd = 0x9ac00c00 | ...
    """
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= xm <= 31
    insn = 0x9ac00c00 | (xm << 16) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_udiv_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """UDIV Xd, Xn, Xm. Unsigned integer division.
    Encoding: 0x9ac00800 | (xm << 16) | (xn << 5) | xd
    """
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= xm <= 31
    insn = 0x9ac00800 | (xm << 16) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_lslv_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """LSLV Xd, Xn, Xm. Shift left (variable). Bottom 6 bits of Xm used.
    Encoding: 0x9ac02000 | (xm << 16) | (xn << 5) | xd
    """
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= xm <= 31
    insn = 0x9ac02000 | (xm << 16) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_lsrv_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """LSRV Xd, Xn, Xm. Logical shift right (variable).
    Encoding: 0x9ac02400 | (xm << 16) | (xn << 5) | xd
    """
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= xm <= 31
    insn = 0x9ac02400 | (xm << 16) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_asrv_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """ASRV Xd, Xn, Xm. Arithmetic shift right (variable).
    Encoding: 0x9ac02800 | (xm << 16) | (xn << 5) | xd
    """
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= xm <= 31
    insn = 0x9ac02800 | (xm << 16) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_msub_xd_xn_xm_xa(xd: int, xn: int, xm: int, xa: int) -> bytes:
    """MSUB Xd, Xn, Xm, Xa. Xd = Xa - Xn * Xm.
    Encoding: 1 0 0 11011 000 Rm 1 Ra Rn Rd = 0x9b008000 | ...

    **The 0..30 range on every field is load-bearing and not cosmetic.** The
    four-operand MADD/MSUB family has no SP form, so architecturally 31 here is
    the zero register and `MSUB Xd, Xn, Xm, XZR` is a perfectly good encoding —
    and `ProofLib.arm64_step`'s MSUB arm would read it correctly. It is still
    refused, because `MUL`'s mask (`0xffe07c00`) and `MSUB`'s (`0xffe08000`) both
    ACCEPT a word with `Ra = 31`, `arm64_step` tests MUL first, and the word is
    then read as `X1 * X5`.  Measured, not reasoned: emitting
    `MSUB X6, X1, X5, XZR` for the `//` correction's negation made
    `formal/examples/udivmod.mojo`'s generated proof fail with the correction
    having the WRONG SIGN.  `_emit_floor_remainder` spells that value with a mask
    instead, and the reason is recorded there and in
    `bugs/FORMAL_arm64_neg_is_shadowed_by_the_sub_register_arm.md`'s
    neighbourhood.
    """
    assert all(0 <= r <= 30 for r in (xd, xn, xm, xa))
    insn = 0x9b008000 | (xm << 16) | (xa << 10) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_lsl_xd_xn_imm(xd: int, xn: int, shift: int) -> bytes:
    """LSL Xd, Xn, #shift (immediate, 0..63). UBFM-based.
    Encoding: UBFM Xd, Xn, #(-shift mod 64), #(63-shift)
    sf=1, opc=10, 100110, N=1 → 0xd3400000 base with immr/imms.
    """
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= shift <= 63
    immr = (-shift) & 63
    imms = 63 - shift
    # 0xd3400000, which is what the docstring above always said. It WAS
    # 0xd3780000, which has `immr = 0b111000` already sitting in bits 21:16, so
    # OR-ing a real `immr` in forced its low three bits to 1 and the shift that
    # RAN was not the one written: 56 of the 64 amounts encoded to some other
    # instruction (1 << 12 came out as 1 << 4, 1 << 0 as 1 << 8). `>>` was and
    # is right, because LSR and ASR are separate encoders and were correct.
    insn = 0xd3400000 | (immr << 16) | (imms << 10) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_asr_xd_xn_imm(xd: int, xn: int, shift: int) -> bytes:
    """ASR Xd, Xn, #shift (immediate, 0..63). SBFM-based.
    Encoding: SBFM Xd, Xn, #shift, #63 → 0x93400000 | shift<<16 | 63<<10
    """
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= shift <= 63
    insn = 0x93400000 | (shift << 16) | (63 << 10) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_lsr_xd_xn_imm(xd: int, xn: int, shift: int) -> bytes:
    """LSR Xd, Xn, #shift (immediate, 0..63). UBFM-based.
    Encoding: UBFM Xd, Xn, #shift, #63 → 0xd3400000 | shift<<16 | 63<<10
    """
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= shift <= 63
    insn = 0xd3400000 | (shift << 16) | (63 << 10) | (xn << 5) | xd
    return struct.pack('<I', insn)


class Assembler:
    """ARM64 assembler with label and relocation support."""

    def __init__(self):
        self.sections: dict[str, bytearray] = {"text": bytearray()}
        self.labels: dict[str, int] = {}
        self.relocs: list[tuple[str, str, int]] = []
        self.extern_refs: list[tuple[str, int, int, str]] = []
        self._org = 0

    def org(self, addr: int):
        """Set the base virtual address."""
        self._org = addr

    def label(self, name: str):
        """Record a label at the current position — once.

        A SECOND binding of the same name is an error rather than a rebinding.
        Every branch is patched out of this table, so a later definition
        silently retargets every earlier reference to it, and what that builds
        is a branch into the middle of a different instruction sequence: the
        image is well formed, the run exits 0, and the answer is a different
        number. Both backends share this because both have shipped it —
        `x86_64.Assembler.label` carries the same check and the longer account,
        and the x86-64 slice-clamp collision it describes
        (fixed 2026-10-03 in 68671a62) is the same defect
        a label name without a per-site counter produces.
        """
        if name in self.labels:
            raise CodegenError(
                f"internal: label {name!r} is defined twice, at 0x"
                f"{self.labels[name]:x} and at 0x"
                f"{self._org + len(self.sections['text']):x}. Branch targets "
                "are patched from this table, so every earlier branch to it now "
                "lands in the middle of this second block. A label name must "
                "carry a per-site counter (see every label in "
                "formal/arm64_codegen.py).")
        self.labels[name] = self._org + len(self.sections["text"])

    def emit(self, data: bytes):
        """Emit raw bytes."""
        self.sections["text"].extend(data)

    def emit_label_rel(self, label_name: str, here_offset: int = 0):
        """Record a relocation for a relative branch/jump.
        here_offset adjusts the position within the instruction (for PC-relative).
        """
        pos = self._org + len(self.sections["text"]) + here_offset
        self.relocs.append(("rel", label_name, pos))

    def emit_extern_bl(self, sym_name: str):
        """Emit a BL instruction to an external symbol (resolved by dynamic linker)."""
        pos = len(self.sections["text"])
        # BL #0 placeholder (will be patched by dynamic linker)
        self.sections["text"].extend(struct.pack('<I', 0x94000000))
        self.extern_refs.append((sym_name, self._org + pos, 4, "bl"))

    def emit_adrp_add(self, xd: int, label: str):
        """Emit ADRP Xd, #page; ADD Xd, Xd, #offset for a label's address.

        Both instructions are emitted as placeholders; the immediate fields
        are back-patched in resolve() once the label's absolute address is
        known (used to load the address of string literals in rodata).
        """
        pos = self._org + len(self.sections["text"])
        # ADRP Xd, #0 (placeholder)
        self.sections["text"].extend(struct.pack('<I', 0x90000000 | xd))
        # ADD Xd, Xd, #0 (placeholder)
        self.sections["text"].extend(
            struct.pack('<I', 0x91000000 | (xd << 5) | xd))
        self.relocs.append(("adrp", label, pos))

    def resolve(self):
        """Backpatch relative branches with correct offsets."""
        for kind, label, pos in self.relocs:
            if label not in self.labels:
                raise ValueError(f"Undefined label: {label}")
            target = self.labels[label]
            idx = pos - self._org

            if kind == "adrp":
                # ADRP Xd, #page (21-bit signed page delta) + ADD Xd, Xd, #off12
                adrp = struct.unpack_from('<I', self.sections["text"], idx)[0]
                xd = adrp & 0x1f
                page_delta = ((target & ~0xfff) - (pos & ~0xfff)) // 4096
                immlo = page_delta & 3
                immhi = (page_delta >> 2) & 0x7ffff
                adrp = 0x90000000 | (immlo << 29) | (immhi << 5) | xd
                struct.pack_into('<I', self.sections["text"], idx, adrp)
                add_off = target & 0xfff
                add_insn = 0x91000000 | (add_off << 10) | (xd << 5) | xd
                struct.pack_into('<I', self.sections["text"], idx + 4, add_insn)
                continue

            # ARM64 branches are PC-relative, offset in 4-byte units
            offset = (target - pos) // 4
            # Find the instruction at pos and patch it
            insn = struct.unpack_from('<I', self.sections["text"], idx)[0]

            if (insn & 0xfc000000) == 0x14000000:
                # B instruction
                insn = (insn & 0xff000000) | (offset & 0x03ffffff)
            elif (insn & 0xfc000000) == 0x94000000:
                # BL instruction
                insn = (insn & 0xff000000) | (offset & 0x03ffffff)
            elif (insn & 0x7e000000) == 0x34000000:
                # CBZ (W or X). imm19 occupies bits 5..23; Rt is bits 0..4
                # and MUST be preserved — the old mask 0xff800000 cleared
                # Rt, turning `cbz x3` into `cbz x0` (and same for CBNZ),
                # so every bounds-check that branched on a non-X0 cset
                # result was silently wrong after resolve().
                insn = (insn & 0xff00001f) | ((offset & 0x7ffff) << 5)
            elif (insn & 0x7e000000) == 0x35000000:
                # CBNZ (W or X) — same imm19/Rt layout as CBZ.
                insn = (insn & 0xff00001f) | ((offset & 0x7ffff) << 5)
            elif (insn & 0xff000000) == 0x54000000:
                # B.cond — imm19 at bits 5..23, cond at bits 3..0. Identified
                # by the top byte alone: masking off the cond bits and then
                # comparing against a zero cond can never match, which is the
                # second version of this bug.
                #
                # Both fields must survive the patch — imm19 is the
                # displacement, cond is WHICH condition is tested. Missing the
                # case entirely is not subtle either: the instruction fell
                # through every branch above, kept imm19 = 0, and branched to
                # ITSELF, so `if a > b:` with a false condition hung the
                # program in a one-instruction loop.
                insn = (insn & 0xff00000f) | ((offset & 0x7ffff) << 5)
            elif (insn & 0xff000000) in (0x36000000, 0x37000000):
                # TBZ / TBNZ — imm14 at bits 5..18, and the PRESERVE mask is
                # 0xfff8001f, NOT the CBZ family's 0xff00001f: bits 19..23 hold
                # the BIT NUMBER (b5) and clearing them made every bit test
                # `tbz w0, #0`, which is a branch on bit 0 of the same word —
                # a wrong answer that builds, runs, and prints. The top byte
                # identifies the pair, and 0x36/0x37 differ only in bit 24, so
                # one `in` test covers both.
                #
                # THE MISSING CASE IS NOT SUBTLE, and this comment exists so it
                # is not reintroduced: with no branch here the instruction fell
                # through every arm above, kept imm14 = 0, and branched to
                # ITSELF — `if x & 8:` hung the program in a one-instruction
                # loop, and `test_arm64_encoders.py` was 424/424 green
                # throughout because it compares the encoder's four bytes and
                # says nothing about a relocation. That is the lesson in
                # `bugs/FORMAL_arm64_instruction_coverage.md` §"Comparing
                # instruction bytes is not comparing instructions", and
                # `test_arm64_emission.py`'s self-branch check is what caught it
                # here.
                insn = (insn & 0xfff8001f) | ((offset & 0x3fff) << 5)

            struct.pack_into('<I', self.sections["text"], idx, insn)
        self.relocs.clear()

    def resolve_extern(self, target_addrs: dict[str, int]):
        """Patch extern BL instructions to branch to a target address.

        Each extern call site is a BL to a __TEXT,__stubs stub; the stub jumps
        through a GOT slot that dyld binds at load time. target_addrs maps each
        symbol to its stub's absolute address.
        """
        for sym_name, pos, instr_len, kind in self.extern_refs:
            if sym_name not in target_addrs:
                raise ValueError(f"Undefined external symbol: {sym_name}")
            target = target_addrs[sym_name]
            # ARM64 BL imm26 is (target - pos) in 4-byte units, signed 26-bit
            offset = (target - pos) // 4
            assert -2**25 <= offset < 2**25
            idx = pos - self._org
            insn = 0x94000000 | (offset & 0x03ffffff)
            struct.pack_into('<I', self.sections["text"], idx, insn)


# ── condition codes, shared by every flag-reading instruction ────────────
# One map, used by CSET/CINC, B.cond, CSEL and friends. These were separate
# literals before, which is how a B.cond ends up testing one code while a CSET
# tests another: the aliases matter (cs/hs and cc/lo are the same bit), so the
# canonical spellings are the primary keys and the aliases resolve to them.
COND_CODES = {
    'eq': 0, 'ne': 1, 'cs': 2, 'hs': 2, 'cc': 3, 'lo': 3,
    'mi': 4, 'pl': 5, 'vs': 6, 'vc': 7, 'hi': 8, 'ls': 9,
    'ge': 10, 'lt': 11, 'gt': 12, 'le': 13, 'al': 14, 'nv': 15,
}


def _cond(cond) -> int:
    if isinstance(cond, int):
        return cond
    try:
        return COND_CODES[cond]
    except KeyError:
        raise ValueError(f"Unknown condition: {cond!r}") from None


# The inverse of each condition, for branching on the FALSE case. The codegen
# always has a "jump here when the condition does not hold" target, so it needs
# the complement of whatever the comparison computed — and computing it by hand
# at each site is how a `<` silently becomes `<=`.
INV_COND = {
    'eq': 'ne', 'ne': 'eq',
    'cs': 'cc', 'hs': 'lo', 'cc': 'cs', 'lo': 'hs',
    'mi': 'pl', 'pl': 'mi',
    'vs': 'vc', 'vc': 'vs',
    'hi': 'ls', 'ls': 'hi',
    'ge': 'lt', 'lt': 'ge',
    'gt': 'le', 'le': 'gt',
    'al': 'nv', 'nv': 'al',
}


def invert_cond(cond: str) -> str:
    """The condition that holds exactly when `cond` does not."""
    try:
        return INV_COND[cond]
    except KeyError:
        raise ValueError(f"Unknown condition: {cond!r}") from None


def encode_b_cond(cond: str, offset: int) -> bytes:
    """B.cond #offset — branch on a comparison's FLAGS.

    The single highest-value instruction this backend was missing. Every
    `if a < b` was lowered as `cmp` + `cset` + `cbz` + branch: three
    instructions, one of which materialises the boolean into a register that
    the branch then immediately reads back. B.cond is `cmp` + branch, and it
    needs no flag-to-register round trip, so a comparison produces a
    dependency on the flags rather than on a value.

    Reach is imm19 (±1MB) against B's imm26, which is the one real constraint
    to watch when a generated function is large.

    `offset` is in BYTES, like encode_b/encode_cbz_xn.
    """
    c = _cond(cond)
    assert c != 14, "B.cond with AL is not encodable; use B"
    # imm19 counts INSTRUCTIONS, so the byte range is +-2^18*4 = +-1MB. Getting
    # this wrong by a factor of two produces a branch that lands 1MB away from
    # where the reloc intended, which no local test would notice.
    assert -2**18 * 4 <= offset < 2**18 * 4, \
        f"B.cond offset {offset} out of range (+-1MB)"
    insn = 0x54000000 | (((offset // 4) & 0x7ffff) << 5) | c
    return struct.pack('<I', insn)


def encode_csel_xd_xm_cond(xd: int, xn: int, xm: int, cond: str) -> bytes:
    """CSEL Xd, Xn, Xm, cond — pick one of two values, branchlessly.

    The reason a conditional EXPRESSION should not become a branch. `a if c
    else b` is two values and a choice, and emitting a branch for it costs a
    label, two jumps and a pipeline flush to move one register. CSEL is one
    instruction and no control flow.

    With Rn = Rm = XZR this is exactly CSET, which is how the existing
    encode_cset_* is expressed.
    """
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= xm <= 31
    c = _cond(cond)
    insn = (0x9A800000 | (xm << 16) | (c << 12) | (xn << 5) | xd)
    return struct.pack('<I', insn)


def encode_csinc_xd_xm_cond(xd: int, xn: int, xm: int, cond: str) -> bytes:
    """CSINC Xd, Xn, Xm, cond — CSEL's incrementing sibling (X + 1)."""
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= xm <= 31
    c = _cond(cond)
    return struct.pack('<I', 0x9A800400 | (xm << 16) | (c << 12) | (xn << 5) | xd)


def encode_csinv_xd_xm_cond(xd: int, xn: int, xm: int, cond: str) -> bytes:
    """CSINV Xd, Xn, Xm, cond — CSEL's inverting sibling (~X)."""
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= xm <= 31
    c = _cond(cond)
    return struct.pack('<I', 0xDA800000 | (xm << 16) | (c << 12) | (xn << 5) | xd)


def encode_csneg_xd_xm_cond(xd: int, xn: int, xm: int, cond: str) -> bytes:
    """CSNEG Xd, Xn, Xm, cond — negate Xm when the condition holds."""
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= xm <= 31
    c = _cond(cond)
    return struct.pack('<I', 0xDA800400 | (xm << 16) | (c << 12) | (xn << 5) | xd)


def encode_tbz_xn_bit(bit: int, xn: int, offset: int) -> bytes:
    """TBZ Xn, #bit, #offset — branch if bit is ZERO. Bits 0-31.

    `if x & (1 << n):` is the shape this exists for, and it is a common one:
    a TST plus a B.cond otherwise, with the mask materialised into a
    register first.

    Bits 0-31 only. The architectural b40 form (bits 32-63) moves imm14 to a
    different field, and rather than encode that from memory of the spec this
    refuses — a wrong branch target is worse than a clear error at emit time.
    Callers with a bit >= 32 should compare against zero with a B.cond after a
    shift."""
    assert 0 <= xn <= 31
    if not 0 <= bit <= 31:
        raise ValueError(
            f"TBZ/TBNZ on bit {bit} is not encodable here (bits 0-31 only); "
            f"use a shift plus a compare, or a mask compare")
    assert -2**13 * 4 <= offset < 2**13 * 4
    insn = 0x36000000 | (((bit & 31) << 19)
                         | (((offset // 4) & 0x3fff) << 5) | xn)
    return struct.pack('<I', insn)


def encode_tbnz_xn_bit(bit: int, xn: int, offset: int) -> bytes:
    """TBNZ Xn, #bit, #offset — branch if bit is NON-ZERO. Bits 0-31."""
    assert 0 <= xn <= 31
    if not 0 <= bit <= 31:
        raise ValueError(
            f"TBZ/TBNZ on bit {bit} is not encodable here (bits 0-31 only); "
            f"use a shift plus a compare, or a mask compare")
    assert -2**13 * 4 <= offset < 2**13 * 4
    insn = 0x36000000 | (1 << 24) | ((bit & 31) << 19) \
        | (((offset // 4) & 0x3fff) << 5) | xn
    return struct.pack('<I', insn)


def encode_ldur_xt_xn_imm(xt: int, xn: int, imm: int) -> bytes:
    """LDUR Xt, [Xn, #imm] — unscaled load, imm a signed 9-bit byte offset.

    LDUR/STUR are how arm64 addresses a displacement that is not a multiple
    of the access size, and in practice that means a NEGATIVE one: a field
    below the frame pointer, or the second half of a pair. Real code emits
    these tens of thousands of times; without them a struct access at a
    negative offset has to be rewritten as an add-then-load.
    """
    assert 0 <= xt <= 30 and 0 <= xn <= 31
    assert -256 <= imm <= 255
    return struct.pack('<I', 0xF8400000 | ((imm & 0x1ff) << 12) | (xn << 5) | xt)


def encode_stur_xt_xn_imm(xt: int, xn: int, imm: int) -> bytes:
    """STUR Xt, [Xn, #imm] — unscaled store, signed 9-bit byte offset."""
    assert 0 <= xt <= 30 and 0 <= xn <= 31
    assert -256 <= imm <= 255
    return struct.pack('<I', 0xF8000000 | ((imm & 0x1ff) << 12) | (xn << 5) | xt)


def encode_ldr_wt_wn_imm(wt: int, wn: int, imm: int = 0) -> bytes:
    """LDR Wt, [Xn, #imm] — load 32 bits, ZERO-extended into Xt.

    The one load of the set that had no encoder here, and it is the unsigned
    4-byte case of the pointer value model's load: `Pointer[UInt32]` and
    `Pointer[SIMDSize]` are 4 bytes, and the alternative was the 8-byte
    `encode_ldr_xt_xn_imm`, which over-reads them by four.  Verified against
    `as`: `ldr w0, [x0]` = 0xb9400000.  Writing Wt rather than Xt is what makes
    it a zero-extend: the 32-bit write clears the top half of Xt, so a formal
    value that is one 64-bit word reads back as the unsigned 32-bit number.
    """
    assert 0 <= wt <= 30 and 0 <= wn <= 31
    assert 0 <= imm <= 16380 and imm % 4 == 0
    return struct.pack('<I', 0xB9400000 | ((imm >> 2) << 10) | (wn << 5) | wt)


def encode_ldrh_wt_wn_imm(wt: int, wn: int, imm: int = 0) -> bytes:
    """LDRH Wt, [Xn, #imm] — load a 16-bit halfword, zero-extended."""
    assert 0 <= wt <= 30 and 0 <= wn <= 31
    assert 0 <= imm <= 16380 and imm % 2 == 0
    return struct.pack('<I', 0x79400000 | ((imm >> 1) << 10) | (wn << 5) | wt)


def encode_strh_wt_wn_imm(wt: int, wn: int, imm: int = 0) -> bytes:
    """STRH Wt, [Xn, #imm] — store the low 16 bits."""
    assert 0 <= wt <= 30 and 0 <= wn <= 31
    assert 0 <= imm <= 16380 and imm % 2 == 0
    return struct.pack('<I', 0x79000000 | ((imm >> 1) << 10) | (wn << 5) | wt)


def encode_ldrsw_xt_xn_imm(xt: int, xn: int, imm: int = 0) -> bytes:
    """LDRSW Xt, [Xn, #imm] — load 32 bits, sign-extend to 64."""
    assert 0 <= xt <= 30 and 0 <= xn <= 31
    assert 0 <= imm <= 16380 and imm % 4 == 0
    return struct.pack('<I', 0xB9800000 | ((imm >> 2) << 10) | (xn << 5) | xt)


def encode_ldrsb_xt_xn_imm(xt: int, xn: int, imm: int = 0) -> bytes:
    """LDRSB Xt, [Xn, #imm] — load a signed byte."""
    assert 0 <= xt <= 30 and 0 <= xn <= 31
    assert 0 <= imm <= 16380
    return struct.pack('<I', 0x39800000 | (imm << 10) | (xn << 5) | xt)


def encode_ldrsh_xt_xn_imm(xt: int, xn: int, imm: int = 0) -> bytes:
    """LDRSH Xt, [Xn, #imm] — load a sign-extended halfword."""
    assert 0 <= xt <= 30 and 0 <= xn <= 31
    assert 0 <= imm <= 16380 and imm % 2 == 0
    return struct.pack('<I', 0x79800000 | ((imm >> 1) << 10) | (xn << 5) | xt)


def encode_tst_xn_xm(xn: int, xm: int) -> bytes:
    """TST Xn, Xm — AND with no destination; sets the flags.

    The flag-setting form of AND, so `if x & mask:` costs a TST and a
    B.cond rather than a full 64-bit AND whose result is then compared
    against zero.
    """
    assert 0 <= xn <= 31 and 0 <= xm <= 31
    return struct.pack('<I', 0xEA00001F | (xm << 16) | (xn << 5))


def encode_cmn_xn_xm(xn: int, xm: int) -> bytes:
    """CMN Xn, Xm — compare (negated); sets flags. The ADD-with-no-result."""
    assert 0 <= xn <= 31 and 0 <= xm <= 31
    return struct.pack('<I', 0xAB00001F | (xm << 16) | (xn << 5))


def encode_subs_xd_xn_xm(xd: int, xn: int, xm: int) -> bytes:
    """SUBS Xd, Xn, Xm — subtract AND set the flags.

    Saves the separate CMP a comparison would otherwise need, at the cost of
    a dependency on the subtraction's result.
    """
    assert 0 <= xd <= 30 and 0 <= xn <= 31 and 0 <= xm <= 31
    return struct.pack('<I', 0xEB000000 | (xm << 16) | (xn << 5) | xd)


def encode_sub_xd_xn_imm_sh(xd: int, xn: int, imm12: int, sh: int = 0) -> bytes:
    """SUB (immediate) with the optional LSL #12 on the 12-bit field.

    Without this, an immediate above 4095 can only be reached by a chain of
    subtractions — and the formal backend subtracts its 128KB scratch from the
    frame pointer at the top of EVERY list base, dict, comprehension and
    container append. 131072 is 32 << 12, so the honest encoding is one
    instruction; the chunked path was emitting thirty-three.

    `sh` selects the shift: 0 is plain, 1 scales imm12 by 4096.
    """
    # 31 is SP, and the function prologue adjusts SP through here.
    assert 0 <= xd <= 31 and 0 <= xn <= 31
    assert 0 <= imm12 <= 0xFFF
    insn = 0xD1000000 | (sh << 22) | (imm12 << 10) | (xn << 5) | xd
    return struct.pack('<I', insn)


def encode_add_xd_xn_imm_sh(xd: int, xn: int, imm12: int, sh: int = 0) -> bytes:
    """ADD (immediate) with the optional LSL #12. See encode_sub_xd_xn_imm_sh."""
    assert 0 <= xd <= 31 and 0 <= xn <= 31
    assert 0 <= imm12 <= 0xFFF
    insn = 0x91000000 | (sh << 22) | (imm12 << 10) | (xn << 5) | xd
    return struct.pack('<I', insn)


# ── IEEE-754 binary64, the SCALAR forms ──────────────────────────────────
#
# A `double` on this path is ONE 64-bit word holding its bit pattern, which is
# why a float needs no new storage anywhere: a parameter, a struct field, a
# list element and a return value are all already words.  What does need new
# instructions is ARITHMETIC, because the word has to reach the machine's
# floating-point unit for the operation to round, propagate NaN and produce
# infinities at all — `ADD` on two bit patterns adds the PATTERNS, which is a
# different number.
#
# The register discipline this section exists to state: **a double's bits live
# in the general register file between operations and in V0..V7 only across
# one.**  Both files are 64 bits wide, `FMOV` moves a pattern between them
# without touching a bit of it, and V0..V7 are caller-saved on AAPCS, so the
# window has to be short — which is exactly the shape of one instruction.  The
# consequence is that everything else on this path (spills, frames, struct
# fields, the register allocator) keeps working on a double with no change,
# and it is why the Lean model needs V0..V7 and nothing else.
#
# Every encoding here is checked against `as -arch arm64` by
# `test_arm64_encoders.py`, which is the oracle rather than a hand-derived bit
# layout.  Register numbers: the `d` operands name the V file by number and are
# 0..31 (`XZR` is 31 for the general side, which is what makes a zero constant
# one instruction).

#: The base word `as` produces for each scalar double operation, with `Rm` in
#: bits 20..16, `Rn` in bits 9..5 and `Rd` in bits 4..0.  One function per
#: operation rather than one taking the mnemonic, because every other encoder in
#: this file is one instruction with one name and
#: `tools/arm64_insn_audit.py` maps an encoder to a base MNEMONIC by its name —
#: a single `encode_fp_alu` covering five mnemonics maps to none of them, and
#: every one of the five then reads as a gap the backend cannot close.
ARM64_FP_BASES = {
    "fadd": 0x1E602800,
    "fsub": 0x1E603800,
    "fmul": 0x1E600800,
    "fdiv": 0x1E601800,
    "fneg": 0x1E614000,
}


def _encode_fp_three(op: str, dd: int, dn: int, dm: int) -> bytes:
    """`Dd op= Dn, Dm` for the four three-operand scalar double operations.

    Both sources are read before the destination is written, so `dd` may be
    either of them (`fadd d0, d0, d1` is what the emitter needs and is what `as`
    produces).
    """
    assert op in ARM64_FP_BASES, op
    assert 0 <= dd <= 31 and 0 <= dn <= 31 and 0 <= dm <= 31
    return struct.pack('<I', ARM64_FP_BASES[op] | (dm << 16) | (dn << 5) | dd)


def encode_fadd_dd_dn_dm(dd: int, dn: int, dm: int) -> bytes:
    """FADD Dd, Dn, Dm — `Dd = Dn + Dm` on doubles, IEEE-754 binary64.

    This and its three siblings are the arithmetic a `double` needs and an
    integer word does not have: the result is ROUNDED to the nearest
    representable double (round-to-nearest-even, ties to even), a NaN operand
    propagates rather than becoming a number, and an overflow becomes an
    infinity. Adding two bit patterns gives a third bit pattern, which is a
    different number, and it is what this backend used to compute for a float
    `+`.
    """
    return _encode_fp_three("fadd", dd, dn, dm)


def encode_fsub_dd_dn_dm(dd: int, dn: int, dm: int) -> bytes:
    """FSUB Dd, Dn, Dm — `Dd = Dn - Dm` on doubles. See `encode_fadd_dd_dn_dm`."""
    return _encode_fp_three("fsub", dd, dn, dm)


def encode_fmul_dd_dn_dm(dd: int, dn: int, dm: int) -> bytes:
    """FMUL Dd, Dn, Dm — `Dd = Dn * Dm` on doubles. See `encode_fadd_dd_dn_dm`."""
    return _encode_fp_three("fmul", dd, dn, dm)


def encode_fdiv_dd_dn_dm(dd: int, dn: int, dm: int) -> bytes:
    """FDIV Dd, Dn, Dm — `Dd = Dn / Dm` on doubles. See `encode_fadd_dd_dn_dm`.

    Division is the operation with no table to check it against in the way
    `+` has one: `1.0/0.0` is `+inf`, `0.0/0.0` is NaN, and `x/0.0` is where
    CPython raises `ZeroDivisionError`. Refusing the constant divisor is
    `formal/model.py`'s decision and not the encoder's, because whether a
    divisor is zero is a fact about the program and only a REFUSAL can say so
    before the program runs.
    """
    return _encode_fp_three("fdiv", dd, dn, dm)


def encode_fneg_dd_dn(dd: int, dn: int) -> bytes:
    """FNEG Dd, Dn — the double in `Dn` with its sign bit flipped.

    Its own instruction and NOT `FSUB Dd, DZR, Dn`, which computes the right
    number for every input except the one that matters: `0.0 - 0.0` is `+0.0`
    where CPython's `-0.0` is `-0.0`. The two compare EQUAL, so a program that
    only compares them cannot tell, and dividing by either gives a different
    answer — which is the shape of a bug that survives a differential test on
    arithmetic and appears on a special value.

    Note that this one takes its source in `Rn` and has no `Rm`, which is the
    same field arrangement `FMOV` uses and not the one the other four use.
    """
    assert 0 <= dd <= 31 and 0 <= dn <= 31
    return struct.pack('<I', ARM64_FP_BASES["fneg"] | (dn << 5) | dd)


def encode_fcmp_dn_dm(dn: int, dm: int) -> bytes:
    """FCMP Dn, Dm — the flag-setting scalar double compare, no result.

    Flags only, like the integer `CMP`, so a conditional branches on them
    directly and a value site `CSET`s from them — the same split
    `encode_cmp_xn_xm` and `encode_cset_xd_cond` make for integers.

    **The flags on NaN are the whole reason the condition this feeds is not the
    integer one.**  IEEE-754 unordered, and ARM's encoding of it, is
    `NZCV = 0011`: `N=0, Z=0, C=1, V=1`.  So of the integer conditions,
    `HI`/`CS` (C=1) are TRUE for an unordered compare and `CC`/`LS` (C=0)
    FALSE.  `a > b` is `HI`, which would make every comparison with a NaN
    true — so `float_condition` below chooses conditions from the other half of
    the flag set, where unordered reads as "false", and swaps the operands for
    the two that need it.  The comparison semantics are decided in
    `formal/model.py`, once, for both backends.
    """
    assert 0 <= dn <= 31 and 0 <= dm <= 31
    return struct.pack('<I', 0x1E602000 | (dm << 16) | (dn << 5))


def encode_fmov_gpr_to_v(dd: int, xn: int) -> bytes:
    """FMOV Dd, Xn — the word's bits into the floating-point file, unchanged.

    A MOVE, not a conversion: this is the instruction a double's storage and its
    arithmetic share, and it is why the representation can be "one word holding
    the bit pattern" without a second one to keep in step.  `xn` may be 31
    (`XZR`), which is `+0.0` as a double — one instruction instead of a
    materialised zero.
    """
    assert 0 <= dd <= 31 and 0 <= xn <= 31
    return struct.pack('<I', 0x9E670000 | (xn << 5) | dd)


def encode_fmov_v_to_gpr(xd: int, dn: int) -> bytes:
    """FMOV Xd, Dn — the other direction of `encode_fmov_gpr_to_v`.

    The instruction to read when a `double` leaves an expression: the codegen's
    contract is that an expression leaves its value in X0, so a float-valued
    expression has to end here or every caller downstream reads a stale word.
    """
    assert 0 <= xd <= 31 and 0 <= dn <= 31
    return struct.pack('<I', 0x9E660000 | (dn << 5) | xd)


def encode_scvtf_dn_xn(dn: int, xn: int) -> bytes:
    """SCVTF Dn, Xn — the signed 64-bit integer in `Xn` as a double.

    The int-to-float half of `float(x)`, and the reason it is not a load of a
    constant: a double's bits are not derivable from an integer's by any
    arithmetic this model performs, so the conversion has to be asked of the
    machine.  Rounding is round-to-nearest-even, which is what CPython's
    `float(2**53 + 1)` answers and what a truncating shift would not.
    """
    assert 0 <= dn <= 31 and 0 <= xn <= 31
    return struct.pack('<I', 0x9E620000 | (xn << 5) | dn)


def encode_fcvtzs_xn_dn(xd: int, dn: int) -> bytes:
    """FCVTZS Xd, Dn — the double in `Dn` truncated toward zero into an integer.

    The float-to-int half of `int(x)`, and "toward zero" is what makes it
    CPython's: `int(2.9)` is 2 and `int(-2.9)` is -2, so this agrees with the
    language.  Note that the name encodes the SATURATION a conversion out of
    range performs — a NaN or an infinity becomes `0x8000000000000000` rather
    than trapping, which is the one documented divergence from CPython (which
    raises); `formal/model.py::float_int_conversion_note` is where that is
    stated, and it is a divergence in an input this path cannot see, not an
    approximation of one it can.
    """
    assert 0 <= xd <= 31 and 0 <= dn <= 31
    return struct.pack('<I', 0x9E780000 | (dn << 5) | xd)
