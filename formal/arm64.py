#!/usr/bin/env python3
"""ARM64 (AArch64) instruction encoder and assembler.

All ARM64 instructions are 4 bytes (32 bits), little-endian encoded.
"""

import struct

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
    Encoding: 000101 0 0 000000 0 0 Rm Rn Rd (sf=1, op=0, m=0) but with negation
    """
    assert 0 <= xd <= 30
    assert 0 <= xn <= 31
    assert 0 <= xm <= 30
    insn = 0x0A200000 | (xm << 16) | (xn << 10) | xd
    return struct.pack('<I', insn)


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
    insn = 0xd3780000 | (immr << 16) | (imms << 10) | (xn << 5) | xd
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
        """Record a label at the current position."""
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
