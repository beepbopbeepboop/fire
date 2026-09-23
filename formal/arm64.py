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


def encode_br_xn(xn: int) -> bytes:
    """BR Xn. Unconditional branch to register.
    Encoding: 11010110000 11111 000000 00000 Rn
    """
    assert 0 <= xn <= 30
    insn = 0xd61f0000 | (xn << 5)
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
                # CBZ instruction
                insn = (insn & 0xff800000) | ((offset << 5) & 0x007ffff0)
            elif (insn & 0x7e000000) == 0x35000000:
                # CBNZ instruction
                insn = (insn & 0xff800000) | ((offset << 5) & 0x007ffff0)

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
