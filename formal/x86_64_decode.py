#!/usr/bin/env python3
"""Instruction-boundary and form decoder for the x86-64 subset this backend emits.

`formal/x86_64.py` is the encoder; this is its inverse, for the two things the
encoder cannot tell you from bytes alone:

  * WHERE each instruction starts.  A proof generator has to name a pc per
    instruction to say anything about it, and a byte string has no such
    structure — the same 0x48 is a prefix in one instruction and an opcode in
    none.
  * WHICH forms the machine model in `lib/ProofLib.lean` has to implement.
    `x86_step` returns `none` for anything it does not decode, so an image
    containing a form the model lacks simply stops executing. The run tests
    the generator emits would then "pass" vacuously (a stopped run reads as
    result 0), which is exactly the kind of quiet wrongness this module exists
    to make visible: `forms()` over a corpus is the checklist for the model.

Scope is deliberately the emitted subset, not x86-64. Every form here has an
`encode_*` counterpart in `formal/x86_64.py`; `test_x86_64_decode.py` pins that
by round-tripping every encoder through this decoder.
"""

import struct
from dataclasses import dataclass

# REX bits, as in formal/x86_64.py's `_rex`.
REX = 0x40
W, R, X, B = 0x08, 0x04, 0x02, 0x01

# ModRM.reg group selectors and condition codes, named the way the form strings
# below name them so a decoded form reads like the instruction it is.
_DIGIT = {0: "add", 1: "or", 4: "and", 5: "sub", 6: "xor", 7: "cmp"}
_SHIFT = {4: "shl", 5: "shr", 7: "sar"}
_GROUP3 = {2: "not", 3: "neg", 4: "mul", 5: "imul1", 6: "div", 7: "idiv"}
_ALU_RR = {0x01: "add", 0x09: "or", 0x21: "and", 0x29: "sub", 0x31: "xor",
           0x39: "cmp", 0x85: "test"}


class DecodeError(Exception):
    """The byte stream does not decode as a known instruction at `offset`."""

    #: `BaseException.args`, declared so the message has a SLOT.  CPython fills
    #: `args` from the caller's arguments and `str(e)` reads it, so
    #: `raise DecodeError(msg)` already carries the text there; an annotation
    #: with no initializer creates no attribute and runs nothing, so this is
    #: invisible to the language and to every reader of this module.
    #:
    #: It is here because `raise DecodeError(msg)` is a CONSTRUCTION with one
    #: argument and this backend fills a struct's fields in DECLARATION ORDER
    #: from positional arguments: a struct that declares no field of its own has
    #: no slot to put the message in, so the call was refused.  Declaring the
    #: field the base class already has is the same program with a
    #: representation.
    args: tuple


@dataclass
class Insn:
    """One decoded instruction.

`form` is the stable identity of the instruction — two instructions with the
    same form have the same effect shape, so the model only has to
    implement each form once. Register fields are already REX-extended (0-15)
    and `mem_base`/`mem_disp` are resolved for a memory operand (`mem_base` is
    None for a register operand and for the RIP-relative form, whose
    displacement is in `rip_rel` and is relative to the NEXT instruction).

    **`xmm` is the exception to "already REX-extended", and it has to be.** For
    every other form `reg` is a GPR index and REX.R widens it to 0-15; for
    `movq_xmm_rm64` the `reg` field names an SSE register, and there is no
    `XMM8` in SysV AMD64, so applying REX.R to it would name a register this
    backend cannot encode. So the XMM number lives in its own field, taken from
    the raw ModRM byte, while `rm` stays the REX.B-extended GPR index.
    """
    offset: int
    length: int
    form: str
    rex: int = 0
    op: int = 0
    reg: int = 0            # ModRM reg field, REX.R applied
    rm: int = 0             # ModRM r/m operand, REX.B applied
    mod: int = 0
    digit: int = 0          # group opcode selector (/digit)
    imm: int = 0
    cc: int = 0             # condition code for jcc/setcc
    mem_base: int | None = None
    mem_disp: int = 0
    rip_rel: int = 0
    xmm: int = 0            # SSE register number, REX.R NOT applied (0-7)

    @property
    def next_offset(self) -> int:
        return self.offset + self.length


def _s8(b: int) -> int:
    return b - 256 if b >= 128 else b


def _s32(v: int) -> int:
    return v - (1 << 32) if v >= (1 << 31) else v


def _i32(code: bytes, at: int) -> int:
    return _s32(struct.unpack_from("<i", code, at)[0])


def _modrm_fields(modrm: int, rex: int, code: bytes, at: int):
    """Decode the ModRM byte (and what follows it) at `at`.

    Returns `(mod, reg, rm, extra, mem_base, mem_disp)` where `extra` counts
    the bytes AFTER the ModRM byte — the SIB byte when rm=4 selects one,
    then the displacement. Order in the stream is ModRM, SIB, disp; getting
    that wrong reads a displacement out of the SIB, which is the kind of bug
    that produces plausible addresses.

    `mem_base` is the register an r/m operand addresses through, or None when
    the operand is a register or RIP-relative.
    """
    mod = modrm >> 6
    reg = ((modrm >> 3) & 7) | (8 if rex & R else 0)
    rm = modrm & 7
    extra = 0
    mem_base = None
    disp = 0
    if mod == 3:
        return mod, reg, rm | (8 if rex & B else 0), extra, None, 0
    if rm == 4:                                   # a SIB byte follows
        sib = code[at + 1]
        extra = 1
        index = (sib >> 3) & 7
        if index != 4:                            # index field 4 = no index
            raise DecodeError(f"SIB with index {index} is not emitted")
        base = (sib & 7) | (8 if rex & B else 0)
        mem_base, rm = base, base
    elif rm == 5 and mod == 0:
        mem_base = None                           # RIP-relative
    else:
        base = rm | (8 if rex & B else 0)
        mem_base, rm = base, base
    if mod == 1:
        disp = _s8(code[at + 1 + extra])
        extra += 1
    elif mod == 2 or (mod == 0 and rm == 5):
        disp = _i32(code, at + 1 + extra)
        extra += 4
    return mod, reg, rm, extra, mem_base, disp


def decode_one(code: bytes, off: int) -> Insn:
    """Decode the single instruction starting at `off`."""
    def byte(i):
        if off + i >= len(code):
            raise DecodeError(f"truncated instruction at {off}")
        return code[off + i]

    p = 0
    rex = 0
    if byte(0) & 0xF0 == REX:
        rex = byte(0)
        p = 1
    # The `0x66` OPERAND-SIZE prefix, read BEFORE the REX byte because that is
    # the order the encoder writes them (`66 REX.W 0F 6E /r`). Reading them the
    # other way round puts the REX test on the prefix byte, finds no REX, and
    # then compares the prefix itself against every opcode below — which is a
    # refusal naming `0x66`, not the instruction.
    #
    # Only one form lives behind it, because only one is emitted:
    # `encode_movq_xmm_rm64`, the GPR-to-SSE move a floating `printf` needs.
    # `lib/X86.lean::x86_step_op66` holds the same restriction and the same
    # reason, and the two have to agree about LENGTH as well as about which
    # opcode: five bytes, prefix included.
    op66 = byte(0) == 0x66
    if op66:
        p += 1
        if byte(p) & 0xF0 == REX:
            rex = byte(p)
            p += 1
    op = byte(p)
    w = bool(rex & W)

    def insn(length, form, **kw):
        return Insn(offset=off, length=length, form=form, rex=rex, op=op, **kw)

    def modrm_at(i, at_mod=None):
        """(fields..., length) for a ModRM instruction whose ModRM is at p+i."""
        mod, reg, rm, extra, base, disp = _modrm_fields(
            byte(p + i), rex, code, off + p + i)
        return mod, reg, rm, extra, base, disp, p + i + 1 + extra

    # ── register-only forms, REX or not ───────────────────────────
    if 0x50 <= op <= 0x57:
        return insn(p + 1, "push_r64", rm=(op & 7) | (8 if rex & B else 0))
    if 0x58 <= op <= 0x5F:
        return insn(p + 1, "pop_r64", rm=(op & 7) | (8 if rex & B else 0))
    if op == 0xC3:
        return insn(1, "ret")
    if op == 0xC9:
        return insn(1, "leave")
    if op == 0x90:
        return insn(1, "nop")
    if op == 0x99 and w:
        return insn(2, "cqo")

    # ── `0x66`-prefixed forms ─────────────────────────────────────
    # `movq xmm, r64` — the direction the backend emits. `0F 6E` is XMM in
    # ModRM.reg and the GPR in rm; `0F 7E` is the reverse, which assembles and
    # links and quietly loads whatever was already in XMM0 into RDI, so it is
    # NOT decoded here and `lib/X86.lean`'s arm refuses it too. REX.W is
    # required because `0F 6E` without it is `MOVD`, which drops all but the low
    # 32 bits and so moves a different VALUE rather than a different placement
    # of the same one.
    #
    # `reg` is the XMM number and carries no REX.R — there is no XMM8 in SysV
    # AMD64 and `encode_movq_xmm_rm64` asserts `0 <= xmm <= 7` — while `rm` is a
    # GPR and does carry REX.B. `_modrm_fields` applies REX.R to `reg`
    # unconditionally, so the XMM number is read off the raw ModRM byte here
    # rather than taken from the helper's `reg`.
    if op66 and op == 0x89:
        # `66 REX 89 /r` — `mov m16, r16`, the 2-byte member of the pointer
        # store set (`encode_mov_rm16_r16`).  It is behind the prefix rather
        # than in the `0x89` arm below because the prefix is what makes it a
        # different INSTRUCTION and not a different width of the same one: with
        # the prefix the opcode is two bytes written, without it four (`89 /r`
        # is `mov rm32, r32`) or eight (REX.W).  `lib/X86.lean::x86_step_op66`
        # is a separate decoder for the same reason, and it takes `0x66` at
        # `rip` and the ModRM at `rip + 3` — one byte further along than the
        # same opcode without the prefix.
        mod, _reg, rm, extra, base, disp, length = modrm_at(1)
        return insn(length, "mov_rm16_r16", mod=mod, rm=rm,
                    mem_base=base, mem_disp=disp)
    if op66 and op == 0x0F and byte(p + 1) == 0x6E and w:
        mod, _reg, rm, extra, _b, _d, length = modrm_at(2)
        if mod != 3:
            raise DecodeError("movq xmm, m64 with a memory operand is not emitted")
        return insn(length, "movq_xmm_rm64", mod=mod,
                    xmm=(byte(p + 2) >> 3) & 7, reg=(byte(p + 2) >> 3) & 7,
                    rm=rm)

    # ── REX-less forms the backend emits ──────────────────────────
    if op == 0x31 and not w:
        # xor rm32, r32 — the REX-less ALU form (`xor edx, edx` before a div).
        mod, reg, rm, extra, _b, _d, length = modrm_at(1)
        if mod != 3:
            raise DecodeError("REX-less xor with a memory operand is not emitted")
        return insn(length, "alu_rr32:xor", mod=mod, reg=reg, rm=rm)
    if 0x70 <= op <= 0x7F:
        return insn(2, "jcc_rel8", cc=op - 0x70, imm=_s8(byte(1)))
    if op == 0xEB:
        return insn(2, "jmp_rel8", imm=_s8(byte(1)))
    if op == 0xE9:
        return insn(5, "jmp_rel32", imm=_i32(code, off + 1))
    if op == 0xE8:
        return insn(5, "call_rel32", imm=_i32(code, off + 1))
    if op == 0xFF:
        form = {0x15: "call_rm64", 0x25: "jmp_rm64"}.get(byte(p + 1))
        if form is None:
            raise DecodeError(f"unsupported 0xFF /{byte(p + 1) & 7} at {off}")
        return insn(p + 6, form, digit=2, rip_rel=_i32(code, off + p + 2))

    # ── REX.W forms ────────────────────────────────────────────────
    if 0xB8 <= op <= 0xBF and w:
        return insn(10, "mov_r64_imm64", rm=(op & 7) | (8 if rex & B else 0),
                    imm=struct.unpack_from("<Q", code, off + 2)[0])
    if op == 0x88:
        # `88 /r` — `mov rm8, r8`, the low BYTE of the reg operand and nothing
        # else (`encode_mov_rm8_r8`).  A member of the pointee-width store set
        # and the reason it exists: the 8-byte form overwrites the seven bytes
        # after a one-byte pointee, which is a silent corruption of a `malloc`ed
        # buffer rather than anything that traps.  NO REX.W — the operand is a
        # byte, so the prefix that would say "64-bit" is the wrong one — and a
        # REX prefix is still emitted when either register is r8-r15, so `rm`
        # and `reg` both come through `_modrm_fields` with REX.B/REX.R applied.
        mod, reg, rm, extra, base, disp, length = modrm_at(1)
        return insn(length, "mov_rm8_r8", mod=mod, reg=reg, rm=rm,
                    mem_base=base, mem_disp=disp)
    if op == 0x89:
        mod, reg, rm, extra, base, disp, length = modrm_at(1)
        if w:
            form = "mov_rm64_r64"
        elif mod == 3:
            form = "mov_rm32_r32"
        else:
            # `89 /r` without REX.W and with a MEMORY operand, which is the one
            # half of the 4-byte store the name `mov_rm32_r32` cannot carry: the
            # register form under that name is a `samples()` row, and its
            # successor reads the register field, so a memory operand given the
            # same name would be handed a successor about a different
            # instruction.
            form = "mov_rm32_r32_mem"
        return insn(length, form, mod=mod, reg=reg, rm=rm,
                    mem_base=base, mem_disp=disp)
    if op == 0x8B:
        # Both widths, and the width is what REX.W decides: with it the load is
        # the 8-byte one, without it `8B /r` is `mov dst32, m32` and ZERO
        # EXTENDS into the 32-bit half (`encode_mov_r32_rm32`, the load
        # counterpart of `mov_rm32_r32`).  Two separate names rather than one
        # name and a flag, because a 4-byte load that reads eight is the hazard
        # this whole family exists to avoid.
        mod, reg, rm, extra, base, disp, length = modrm_at(1)
        form = "mov_r64_rm64" if w else "mov_r32_rm32"
        return insn(length, form, mod=mod, reg=reg, rm=rm,
                    mem_base=base, mem_disp=disp)
    if op == 0x8D and w:
        mod, reg, rm, extra, base, disp, length = modrm_at(1)
        # mod=00 with rm=101 is the RIP-relative form of the r/m field (and
        # carries NO SIB byte); anything else is a base+disp address.
        rip = (mod == 0 and (byte(p + 1) & 7) == 5)
        return insn(length, "lea_r64_rip" if rip else "lea_r64_rm64",
                    mod=mod, reg=reg, rm=rm, mem_base=base, mem_disp=disp,
                    rip_rel=disp if rip else 0)
    if op == 0x63 and w:
        mod, reg, rm, extra, base, disp, length = modrm_at(1)
        # The register form is `movsxd_r64_r32`; the memory form is named after
        # its encoder, `encode_movsx_r64_rm32`, and is a different instruction
        # to the model (it is a DEREFERENCE).
        form = "movsxd_r64_r32" if mod == 3 else "movsx_r64_rm32"
        return insn(length, form, mod=mod, reg=reg, rm=rm,
                    mem_base=base, mem_disp=disp)
    if op == 0xC7 and w:
        mod, reg, rm, extra, base, disp, length = modrm_at(1)
        if mod != 3:
            raise DecodeError("mov rm64, imm32 with a memory operand "
                              "is not emitted")
        return insn(p + 6, "mov_rm64_imm32", mod=mod, rm=rm,
                    imm=_i32(code, off + p + 2))
    if op == 0x99 and w:
        return insn(2, "cqo")

    # ── 0x0F-escaped forms ────────────────────────────────────────
    if op == 0x0F:
        op2 = byte(p + 1)
        if 0x90 <= op2 <= 0x9F and not w:
            mod, reg, rm, extra, base, disp, length = modrm_at(2)
            if mod != 3:
                raise DecodeError("setcc with a memory operand is not emitted")
            return insn(length, "setcc", cc=op2 - 0x90, mod=mod, rm=rm)
        if 0x80 <= op2 <= 0x8F:
            return insn(6, "jcc_rel32", cc=op2 - 0x80,
                        imm=_i32(code, off + 2))
        if op2 in (0xB6, 0xB7, 0xBE, 0xBF):
            # Both operand kinds, and the SIB and displacement bytes are what
            # make the memory half different rather than merely wider: the
            # instruction is three bytes for a register operand and
            # three-plus-the-displacement for a memory one, and a decoder that
            # resumes at a fixed `+ 3` walks into its own displacement.  That is
            # the defect `lib/X86.lean` had for these four, and it is why the
            # length here comes from `_modrm_fields` rather than from a
            # constant.
            #
            # The MEMORY forms are named after their ENCODER, which is what
            # this module is the inverse of, so `movzx_r64_rm8` is
            # `encode_movzx_r64_rm8` and `movzx_r64_r8` is the register one.
            # They have to be different names because they are different
            # instructions — `lib/X86.lean` reaches the REX.W memory ones
            # through `x86_step_rex` and the no-REX ones through the `0x0F` arm
            # — and one name for both would make `_resolve` apply one lemma and
            # one successor to both, which for a memory operand is a WRONG
            # successor rather than a missing one.
            #
            # The split is the OPERAND KIND, not REX.W, and that is not a
            # restatement: `encode_movzx_r64_rm8` emits `0F B6` with NO REX.W
            # (the destination is written as a 32-bit register, which
            # zero-extends) while `encode_movsx_r64_rm8` emits REX.W `0F BE`.
            # Deciding on `w` names the byte load `movzx_r64_r8` — a register
            # form, with a successor that reads RDX — which is how a
            # `samples()` row and the decoder's own answer come to disagree
            # about an instruction both of them are right about.
            names = {0xB6: ("movzx_r64_r8", "movzx_r64_rm8"),
                     0xB7: ("movzx_r64_r16", "movzx_r64_rm16"),
                     0xBE: ("movsx_r64_r8", "movsx_r64_rm8"),
                     0xBF: ("movsx_r64_r16", "movsx_r64_rm16")}[op2]
            mod, reg, rm, extra, base, disp, length = modrm_at(2)
            form = names[0] if mod == 3 else names[1]
            return insn(length, form, mod=mod, reg=reg, rm=rm,
                        mem_base=base, mem_disp=disp)
        if op2 == 0xAF and w:
            mod, reg, rm, extra, base, disp, length = modrm_at(2)
            if mod != 3:
                raise DecodeError("imul with a memory operand is not emitted")
            return insn(length, "imul_r64_r64", mod=mod, reg=reg, rm=rm)

    # ── ALU and shifts, REX.W ──────────────────────────────────────
    if w and (alu := _ALU_RR.get(op)) is not None:
        mod, reg, rm, extra, base, disp, length = modrm_at(1)
        if mod != 3:
            raise DecodeError(f"ALU {alu} with a memory operand is not emitted")
        return insn(length, f"alu_rr:{alu}", mod=mod, reg=reg, rm=rm)
    if w and op in (0x81, 0x83):
        mod, reg, rm, extra, base, disp, length = modrm_at(1)
        if mod != 3:
            raise DecodeError("ALU with an immediate and a memory operand "
                              "is not emitted")
        digit = (byte(p + 1) >> 3) & 7
        if op == 0x81:
            return insn(p + 6, f"alu_ri32:{_DIGIT[digit]}", mod=mod, rm=rm,
                        digit=digit, imm=_i32(code, off + p + 2))
        return insn(p + 3, f"alu_ri8:{_DIGIT[digit]}", mod=mod, rm=rm,
                    digit=digit, imm=_s8(byte(p + 2)))
    if w and op in (0xC1, 0xD3):
        mod, reg, rm, extra, base, disp, length = modrm_at(1)
        if mod != 3:
            raise DecodeError("shift with a memory operand is not emitted")
        digit = (byte(p + 1) >> 3) & 7
        if op == 0xC1:
            return insn(p + 3, f"shift_imm8:{_SHIFT[digit]}", mod=mod, rm=rm,
                        digit=digit, imm=byte(p + 2))
        return insn(p + 2, f"shift_cl:{_SHIFT[digit]}", mod=mod, rm=rm,
                    digit=digit)
    if w and op == 0xF7:
        mod, reg, rm, extra, base, disp, length = modrm_at(1)
        if mod != 3:
            raise DecodeError("group3 with a memory operand is not emitted")
        digit = (byte(p + 1) >> 3) & 7
        return insn(length, f"group3:{_GROUP3[digit]}", mod=mod, rm=rm, digit=digit)

    raise DecodeError(f"undecodable byte 0x{op:02x} (rex 0x{rex:02x}) at {off}")


def decode_all(code: bytes, start: int = 0, end: int = None) -> list:
    """Linear sweep from `start` to `end`, returning every instruction.

    A linear sweep is the right shape here because the backend lays the image
    out as one contiguous run of instructions (the startup stub, then every
    function back to back) followed by the string/data pool — the caller
    passes `end` = the first data label, so data bytes are never offered to
    the decoder."""
    end = len(code) if end is None else end
    out = []
    off = start
    while off < end:
        insn = decode_one(code, off)
        if off + insn.length > end:
            raise DecodeError(
                f"instruction at {off} runs {insn.length} bytes past the end {end}")
        out.append(insn)
        off = insn.next_offset
    return out


def forms(insns: list) -> set:
    """The set of distinct `form` values — the model's implementation checklist."""
    return {i.form for i in insns}
