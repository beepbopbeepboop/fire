#!/usr/bin/env python3
"""Does lib/ProofLib.lean's arm64 machine model agree with an arm64 CPU?

**THE SIBLING, and there are two of these on purpose.**
`formal/x86_64_model_fuzz.py` asks the same question of `lib/X86.lean` against
an x86-64 CPU, and the two are NOT one program with a `--arch` flag. That was
measured rather than assumed: of the x86 file's 747 non-comment source lines,
**8 are byte-identical to a line here** (1.1%), and they are `memset`,
`printf` and two Lean `match` arms. The pools are different encoders from
different modules (`formal/arm64.py` vs `formal/x86_64.py`), the address models
differ (a translated window versus one `MAP_FIXED` region at a fixed base), the
verdict sets differ (`ENC-MISMATCH`/`NOSTEP` here, `HARNESS`/`NORUN` there), and
so do the Lean halves and their launch strategies. What a single shared
implementation would actually be is an argument-parser and a reporting loop —
which is what `tools/tu_grind.py` already is, and why neither harness grew its
own copy of the scratch-directory policy. So: two files, one question, and this
paragraph so that the next reader does not spend an hour trying to merge them.

Every proof in this repository is a theorem about `arm64_step`. A model that
disagrees with the machine makes all of them vacuous, and nothing in the tree
can see it: `lib/ProofLib.lean`'s definitions are trivially well-typed, so a
wrong shift amount, a missing 32-bit truncation or a hardwired base register
is a green build and a false theorem. The only check that means anything is
running the model and the hardware on the SAME BYTES and comparing the state.

So this is a differential harness, in three parts.

**The instruction pool is the encoders the backend actually emits.**
`formal/arm64.py`'s `encode_*` chooses each instruction and its operand
registers; `tools/arm64_insn_audit.py::unwired_encoders` says which of those
encoders no lowering in `formal/` references, and the pool is the wired ones —
the encodings an image can actually contain. Every generated case is also
cross-checked against `as -arch arm64`: the bytes the hardware runs are the
ASSEMBLER's, and an encoder that disagrees is reported as `ENC-MISMATCH` rather
than silently charged to the model. Without that, an encoder bug and a model
bug look identical, and the harness would spend its findings on the wrong one.

**Both engines run the same code bytes.** The native side is a generated
Mach-O function per case (see `STUB` below) that installs an arbitrary
register/flag/memory state, runs the case's instructions, and dumps X0-X30,
SP, NZCV, PC and the whole memory window. The Lean side is one `#eval` per case
calling `arm64_step` the same number of times. Registers, flags and memory are
then compared byte for byte.

**Three verdicts, not one.** `AGREE`; `WRONG`, where both engines ran to the
end and the final state differs — that is a model bug, and `--minimise` reduces
it to a one- or two-instruction case; and `NOSTEP`, where `arm64_step` answered
`none` for an instruction the backend emits — a refusal, which is a different
and worse failure than a wrong answer, because a proof that cannot step an
instruction is a proof about nothing. `FAULT` (the CPU took a signal) and
`ENC-MISMATCH` (our encoder disagrees with the assembler) are counted
separately from both, because neither is evidence about the model.

Usage:
    python3 tools/formal_model_fuzz.py                       # 200 cases, all mixes
    python3 tools/formal_model_fuzz.py --cases 500 --seed sweepB
    python3 tools/formal_model_fuzz.py --mix alu --verbose   # one mix, per-case
    python3 tools/formal_model_fuzz.py --regressions         # the fixed corpus
    python3 tools/formal_model_fuzz.py --keep .tmp/fmwork    # keep the artifacts
Exit: 0 iff every case agrees and nothing is refused or mismatched.
"""

import argparse
import collections
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from formal import arm64 as A                                       # noqa: E402
import formal.lean as L                                             # noqa: E402


# ── the memory window, and how the two engines' address spaces line up ───
#
# The model's memory is `Nat → UInt8` and its SP is a compile-time constant
# (MODEL_SP), so a model address IS the offset from MODEL_SP. The hardware's
# SP is a runtime address in an mmap'd window, so a hardware address is
# `window + offset`. Comparing the two byte for byte therefore means comparing
# the same OFFSET on both sides, and every offset has to stay inside the
# compared window — an access outside it is a harness limitation (the model
# would read 0 where the CPU reads whatever is mapped there), not a model bug,
# so the generator keeps every address in range by construction and says so.
MODEL_SP = 256
"""The model's SP. Any value works; it is what makes model addresses Nats."""
MEM_NEG = 32            # most negative immediate offset the pool emits
MEM_IMM = 64            # exclusive bound on a positive immediate offset
MEM_A = 32              # the window an address REGISTER may point into
MEM_LO = MODEL_SP - MEM_NEG - 8      # first compared byte, model coordinates
MEM_HI = MODEL_SP + MEM_A + MEM_IMM + 8   # one past the last compared byte
DUMP_OFF = MEM_HI      # the epilogue's dump band starts here (model coords)
SLOT_PC_END = DUMP_OFF + 256    # the pc after the case's last instruction
SLOT_PROBE = DUMP_OFF + 264      # X16 after the four-branch flag probe
SLOT_PC_START = DUMP_OFF + 272   # the pc the case's first instruction sat at

#: `MSR NZCV, Xt` and `MRS Xt, NZCV` are NO-OPS in EL0 on this platform.
#: Measured 2026-10-04, macOS 25.6 / arm64, clang 21: a two-instruction
#: `msr nzcv, x0` / `mrs x1, nzcv` with x0 = 6 reads back 0, for every one of
#: the sixteen values, and so does every other source register. (An earlier test
#: appeared to round-trip all sixteen and was wrong: its inline-asm output
#: operand was allocated the same register as its input, so it read the input
#: back.) PSTATE.NZCV is not user-writable on Apple silicon, so the harness
#: cannot SET the initial flags and cannot READ the final ones that way.
#:
#: Both are replaced by real instructions, which is strictly better evidence
#: anyway: the flags a case starts with are ESTABLISHED by a `cmp` both engines
#: execute (so they are equal by construction rather than by arrangement), and
#: the flags a case ends with are READ BACK by four conditional branches whose
#: taken/not-taken pattern spells N, Z, C and V.
STASH_OFF = -128       # where the stub parks the C frame pointer, in window coords
MODEL_PC = 1024        # the model's initial pc; only DIFFERENCES are compared
MAX_INSNS = 6          # a case is short on purpose: state is what is compared

ADDR_REGS = (9, 17)
OFF_REG = 21
"""The two registers that may be a memory BASE.

They are the only registers whose two engines' values differ, and deliberately:
a base register names an absolute address, and the hardware's absolute address
is a runtime address the model cannot know. So the pool initialises them to
`MODEL_SP + a` in the model and to `window + a` on the hardware — the same `a`,
the same memory. They are never a destination (so they still hold that value at
the end and the translation stays valid), they may be a source anywhere else,
and the harness compares them translated. Every OTHER register is
byte-identical on both sides."""

CASES_PER_MIX = 40


# ── the native stub, once, as a string per case ─────────────────────────
#
# No `adrp`: the pointer comes in as an argument and the dump goes out through
# SP, so the stub needs no absolute address and therefore no relocation and no
# known load slide. Everything it touches is either an argument or
# SP-relative. `mov x30, x0` is the table base and `ldr x30, [x30, #240]` is the
# last load, so all 31 GPRs carry their case value and NONE of them is reserved
# for the harness — a reserved register would be a register the model never
# gets to disagree about.
STUB_HEAD = """
    sub  sp, sp, #96
    stp  x19, x20, [sp, #0]
    stp  x21, x22, [sp, #16]
    stp  x23, x24, [sp, #32]
    stp  x25, x26, [sp, #48]
    stp  x27, x28, [sp, #64]
    stp  x29, x30, [sp, #80]
    ldr  x16, [x0, #248]
    mov  x17, sp
    stur x17, [x16, #-128]
    mov  sp, x16
"""
# The start-pc record, then the table loads. It has to be HERE and not before
# the loads: every one of the 31 registers carries a case value, so a temporary
# used after the loads would be a register the case can no longer have — and
# X16 is loaded by the third `ldp`, so it has to be spent before that. X16 is
# free here because SP has just been set from it.
STUB_HEAD += "    adr  x16, 4f\n    str  x16, [sp, #%d]\n" % (DUMP_OFF + 272)
STUB_HEAD += "    mov  x30, x0\n"
# 15 pairs cover slots 0..29; slot 30 (X30, the base register itself) is loaded
# last, self-referentially, so the base survives until the final instruction.
for _i in range(15):
    STUB_HEAD += "    ldp  x%d, x%d, [x30, #%d]\n" % (2 * _i, 2 * _i + 1, 16 * _i)
STUB_HEAD += "    ldr  x30, [x30, #240]\n4:\n"

#: The epilogue, in this order and not another one:
#:
#:   1. dump X0-X30. This is where X16's slot is written, so the probe below has
#:      a BASELINE to be subtracted from — and the probe accumulates into X16,
#:      so it must run before anything else spends that register (an earlier
#:      version recorded SP and the pc first, and the probe then measured from a
#:      code address: the reconstructed NZCV was a function of where the harness
#:      happened to be loaded).
#:   2. the flag probe — one `9:` after EVERY `add`, because a numeric local
#:      label is reused by definition and a single `9:` at the end makes all
#:      three branches skip all three adds (measured: the reconstructed NZCV
#:      came out as a value no subtraction can produce, N=1 with Z=1).
#:   3. record SP and the pc. `2:` is the epilogue's first instruction, which is
#:      the address the model's `arm64_steps` lands on, and `adr` gets there from
#:      anywhere in the function, so the order of 2 and 3 does not matter to it.
STUB_TAIL_BODY = ""
for _i in range(31):
    STUB_TAIL_BODY += "    str  x%d, [sp, #%d]\n" % (_i, DUMP_OFF + 8 * _i)
STUB_TAIL_BODY += """    b.mi 9f
    add  x16, x16, #1
9:  b.eq 9f
    add  x16, x16, #2
9:  b.cs 9f
    add  x16, x16, #4
9:  b.vs 9f
    add  x16, x16, #8
9:  str  x16, [sp, #%d]
    add  x16, sp, #0
    str  x16, [sp, #%d]
    adr  x16, 2b
    str  x16, [sp, #%d]
    ldr  x16, [sp, #-128]
    mov  sp, x16
""" % (SLOT_PROBE, DUMP_OFF + 248, SLOT_PC_END)
for _i in range(6):
    STUB_TAIL_BODY += "    ldp  x%d, x%d, [sp, #%d]\n" % (19 + 2 * _i, 20 + 2 * _i, 16 * _i)
STUB_TAIL_BODY += "    add  sp, sp, #96\n    ret\n"
PROBE_BITS = 4      # the probe adds this many bits to x16, one per flag


class Case(object):
    """One differential test: a state, and the instructions to run on it."""

    __slots__ = ("regs", "nzcv", "mem", "texts", "words", "n", "mix")

    def __init__(self, regs, nzcv, mem, texts, words):
        self.regs = regs        # 32 UInt64: X0..X30 then SP
        self.nzcv = nzcv        # the PSTATE.NZCV the case starts with
        self.mem = mem          # (MEM_HI - MEM_LO) bytes at [MEM_LO, MEM_HI)
        self.texts = texts      # the case's instructions, as assembly text
        self.words = words      # their encodings as instruction words (ints)
        self.n = len(texts)
        self.mix = ""

    def describe(self):
        out = ["  %d instruction(s), nzcv=0x%x" % (self.n, self.nzcv)]
        for r in ADDR_REGS:
            out.append("  base register x%d = MODEL_SP + %d" % (r, self.regs[r] - MODEL_SP))
        for t in self.texts:
            out.append("    " + t)
        return "\n".join(out)


# ── the instruction pool ────────────────────────────────────────────────
#
# Each generator returns assembly TEXT plus the encoding `formal/arm64.py`
# claims for it. The text is what the hardware runs; the encoding is what gets
# compared against `as`, so a disagreement is an encoder finding and not a
# model finding. Registers are drawn from `free_regs` (everything but the two
# base registers, which are never a destination) and 31, which the model reads
# as SP in the forms that have an SP encoding and as the zero register in the
# forms that do not — the same split `arm64_reg_or_sp` exists to express.
CONDS = ("eq", "ne", "cs", "cc", "mi", "pl", "vs", "vc", "hi", "ls", "ge", "lt",
         "gt", "le")


def _r(rng, free):
    return rng.choice(free)


def _dst(rng, free):
    return _r(rng, free)


def _imm_off(rng):
    """An in-window signed immediate offset for a byte-granular access."""
    if rng.random() < 0.25:
        return -rng.randrange(1, MEM_NEG + 1)
    return 8 * rng.randrange(0, MEM_IMM // 8 + 1)


def _base(rng):
    return rng.choice((31,) + ADDR_REGS)


def _rn(r):
    """A register's assembly NAME. 31 is `sp` in a memory operand's base
    position — `as` rejects `x31` there with "invalid operand for instruction" —
    and `xzr` nowhere else, so only the base position goes through this."""
    return "sp" if r == 31 else "x" + str(r)


def gen_alu(rng, free):
    d, n, m = _dst(rng, free), _r(rng, free), _r(rng, free)
    i = rng.randrange(0x1000)
    k = rng.randrange(9)
    if k == 0:
        return "add x%d, x%d, x%d" % (d, n, m), A.encode_add_xd_xn_xm(d, n, m)
    if k == 1:
        return "add x%d, x%d, #%d" % (d, n, i), A.encode_add_xd_xn_imm(d, n, i)
    if k == 2:
        return "sub x%d, x%d, x%d" % (d, n, m), A.encode_sub_xd_xn_xm(d, n, m)
    if k == 3:
        return "sub x%d, x%d, #%d" % (d, n, i), A.encode_sub_xd_xn_imm(d, n, i)
    if k == 4:
        return "and x%d, x%d, x%d" % (d, n, m), A.encode_and_xd_xn_xm(d, n, m)
    if k == 5:
        return "orr x%d, x%d, x%d" % (d, n, m), A.encode_orr_xd_xn_xm(d, n, m)
    if k == 6:
        return "eor x%d, x%d, x%d" % (d, n, m), A.encode_eor_xd_xn_xm(d, n, m)
    if k == 7:
        # `encode_and_xd_xn_imm`'s third argument is the MASK WIDTH: it emits
        # the canonical `AND (immediate)` word for #0xff / #0xffff /
        # #0xffffffff, so the text has to say that immediate and not the width.
        # (The other encodings of the same logical immediate exist — Apple's
        # assembler emits `and x0, x1, #16` as immr=60/imms=0 rather than
        # immr=0/imms=4 — and `arm64_step` refuses those, which is why the pool
        # emits the canonical words and not "whatever `as` would print".)
        w = rng.choice((8, 16, 32))
        return ("and x%d, x%d, #%d" % (d, n, (1 << w) - 1),
                A.encode_and_xd_xn_imm(d, n, w))
    return "mvn x%d, x%d" % (d, n), A.encode_mvn_xd_xn(d, n)


def gen_moves(rng, free):
    """The move-immediate family, one encoder per width.

    `formal/arm64.py` has TWO `movz` encoders and they are not
    interchangeable: `encode_movz_xd_imm` is the 64-bit one (base `0xd2800000`)
    and `encode_movz_wd_imm` is the 32-bit one (base `0x52800000`), which is
    what every `arm64_codegen.py` call site emits. The pool pairs each encoder
    with the WIDTH ITS OWN BASE ENCODES, because the alternative — pairing a
    32-bit encoder with the text `movz xN` — makes every one of those draws an
    `ENC-MISMATCH` and buries the real findings under a defect in the pool.

    **The two names used to be the other way round**, which is why the pairing
    is worth stating: the 32-bit encoder was called `encode_movz_xd_imm` and the
    64-bit one `encode_movz_xn_imm`, so pairing by NAME gave the wrong width
    for both and `ENC-MISMATCH 8 of 60` on the first sweep. Each is named after
    the width it encodes now, and `test_arm64_encoders.py` checks both widths
    of both names against `as -arch arm64` — so this pool's rule is now also
    the encoder table's, rather than a convention this one file remembers.
    """
    d, n = _dst(rng, free), _r(rng, free)
    i = rng.randrange(0x10000)
    k = rng.randrange(5)
    if k == 0:
        return "movz x%d, #%d" % (d, i), A.encode_movz_xd_imm(d, i)
    if k == 1:
        return "movz w%d, #%d" % (d, i), A.encode_movz_wd_imm(d, i)
    if k == 2:
        return "mov x%d, x%d" % (d, n), A.encode_mov_zr_xn(d, n)
    if k == 3:
        p = 16 * rng.randrange(4)      # the encoder's `pos` is a BIT offset
        return "movk x%d, #%d, lsl #%d" % (d, i, p), \
            A.encode_movk_xd_imm(d, i, p)
    return "movn w%d, #%d" % (d, i), A.encode_movn_wd_imm(d, i)


def gen_flags(rng, free):
    d, n, m = _dst(rng, free), _r(rng, free), _r(rng, free)
    i = rng.randrange(0x1000)
    k = rng.randrange(4)
    if k == 0:
        return "cmp x%d, #%d" % (n, i), A.encode_cmp_xn_imm(n, i)
    if k == 1:
        return "cmp x%d, x%d" % (n, m), A.encode_cmp_xn_xm(n, m)
    if k == 2:
        return "subs x%d, x%d, x%d" % (d, n, m), A.encode_subs_xd_xn_xm(d, n, m)
    return "cmn x%d, x%d" % (n, m), A.encode_cmn_xn_xm(n, m)


def gen_shifts(rng, free):
    d, n, m = _dst(rng, free), _r(rng, free), _r(rng, free)
    sh = rng.randrange(64)
    k = rng.randrange(6)
    if k == 0:
        return "lsl x%d, x%d, #%d" % (d, n, sh), A.encode_lsl_xd_xn_imm(d, n, sh)
    if k == 1:
        return "lsr x%d, x%d, #%d" % (d, n, sh), A.encode_lsr_xd_xn_imm(d, n, sh)
    if k == 2:
        return "asr x%d, x%d, #%d" % (d, n, sh), A.encode_asr_xd_xn_imm(d, n, sh)
    if k == 3:
        return "lslv x%d, x%d, x%d" % (d, n, m), A.encode_lslv_xd_xn_xm(d, n, m)
    if k == 4:
        return "lsrv x%d, x%d, x%d" % (d, n, m), A.encode_lsrv_xd_xn_xm(d, n, m)
    return "asrv x%d, x%d, x%d" % (d, n, m), A.encode_asrv_xd_xn_xm(d, n, m)


def gen_muldiv(rng, free):
    d, n, m, a = _dst(rng, free), _r(rng, free), _r(rng, free), _r(rng, free)
    k = rng.randrange(5)
    if k == 0:
        return "mul x%d, x%d, x%d" % (d, n, m), A.encode_mul_xd_xn_xm(d, n, m)
    if k == 1:
        return "msub x%d, x%d, x%d, x%d" % (d, n, m, a), \
            A.encode_msub_xd_xn_xm_xa(d, n, m, a)
    if k == 2:
        return "udiv x%d, x%d, x%d" % (d, n, m), A.encode_udiv_xd_xn_xm(d, n, m)
    if k == 3:
        return "sdiv x%d, x%d, x%d" % (d, n, m), A.encode_sdiv_xd_xn_xm(d, n, m)
    return "neg x%d, x%d" % (d, n), A.encode_neg_xd_xn(d, n)


def gen_select(rng, free):
    d, n, m = _dst(rng, free), _r(rng, free), _r(rng, free)
    c = rng.choice(CONDS)
    if rng.random() < 0.5:
        return "csel x%d, x%d, x%d, %s" % (d, n, m, c), \
            A.encode_csel_xd_xm_cond(d, n, m, c)
    return "cset x%d, %s" % (d, c), A.encode_cset_xd_cond(d, c)


def gen_ext(rng, free):
    """SXTB/SXTH/SXTW as `formal/arm64.py` encodes them.

    The destination is spelled `w` for the first two because that IS what those
    encoders emit: `encode_sxtb_wd_wn` is the 32-bit form (0x13001c00), and the
    64-bit-destination spelling assembles to a DIFFERENT word (0x93401c00) that
    `arm64_step` has no arm for — so writing `sxtb x0, w1` here would report the
    model's coverage as a defect of the pool, which is the failure mode the
    disassembly cross-check exists to prevent.
    """
    d, n = _dst(rng, free), _r(rng, free)
    k = rng.randrange(3)
    if k == 0:
        return "sxtb w%d, w%d" % (d, n), A.encode_sxtb_wd_wn(d, n)
    if k == 1:
        return "sxth w%d, w%d" % (d, n), A.encode_sxth_wd_wn(d, n)
    return "sxtw x%d, w%d" % (d, n), A.encode_sxtw_xd_wn(d, n)


def gen_mem(rng, free):
    """A load or store whose address is in the compared window, always.

    The base is SP or one of the two base registers, and the offset is bounded
    so that base+offset+width stays inside `[MEM_LO, MEM_HI)`. Both bounds are
    part of the GENERATOR rather than of the comparison, because an access
    outside the window is a limit of THIS harness (the model's memory is a
    function of Nats that answers 0 outside the window; the CPU's is a mapped
    page) and not a fact about `arm64_step`.
    """
    k = rng.randrange(12)
    base = _base(rng)
    d = _dst(rng, free)
    if k in (0, 1):
        off = 8 * rng.randrange(0, MEM_IMM // 8 + 1)
        if k == 0:
            return ("ldr x%d, [%s, #%d]" % (d, _rn(base), off),
                    A.encode_ldr_xt_xn_imm(d, base, off))
        return ("str x%d, [%s, #%d]" % (d, _rn(base), off),
                A.encode_str_xt_xn_imm(d, base, off))
    if k in (2, 3):
        off = 4 * rng.randrange(0, MEM_IMM // 4 + 1)
        if k == 2:
            return ("ldr w%d, [%s, #%d]" % (d, _rn(base), off),
                    A.encode_ldr_wt_wn_imm(d, base, off))
        return ("str w%d, [%s, #%d]" % (d, _rn(base), off),
                A.encode_str_wt_wn_imm(d, base, off))
    if k == 4:
        off = rng.randrange(0, MEM_IMM + 1)
        return ("ldrb w%d, [%s, #%d]" % (d, _rn(base), off),
                A.encode_ldrb_wd_wn(d, base, off))
    if k == 5:
        off = rng.randrange(0, MEM_IMM + 1)
        return ("strb w%d, [%s, #%d]" % (d, _rn(base), off),
                A.encode_strb_wd_wn(d, base, off))
    if k == 6:
        off = 2 * rng.randrange(0, MEM_IMM // 2 + 1)
        return ("ldrh w%d, [%s, #%d]" % (d, _rn(base), off),
                A.encode_ldrh_wt_wn_imm(d, base, off))
    if k == 7:
        off = 2 * rng.randrange(0, MEM_IMM // 2 + 1)
        return ("strh w%d, [%s, #%d]" % (d, _rn(base), off),
                A.encode_strh_wt_wn_imm(d, base, off))
    if k == 8:
        off = 4 * rng.randrange(0, MEM_IMM // 4 + 1)
        return ("ldrsw x%d, [%s, #%d]" % (d, _rn(base), off),
                A.encode_ldrsw_xt_xn_imm(d, base, off))
    if k == 9:
        off = rng.randrange(0, MEM_IMM + 1)
        return ("ldrsb x%d, [%s, #%d]" % (d, _rn(base), off),
                A.encode_ldrsb_xt_xn_imm(d, base, off))
    if k == 10:
        off = 2 * rng.randrange(0, MEM_IMM // 2 + 1)
        return ("ldrsh x%d, [%s, #%d]" % (d, _rn(base), off),
                A.encode_ldrsh_xt_xn_imm(d, base, off))
    off = _imm_off(rng)
    if rng.random() < 0.5:
        return ("ldur x%d, [%s, #%d]" % (d, _rn(base), off),
                A.encode_ldur_xt_xn_imm(d, base, off))
    return ("stur x%d, [%s, #%d]" % (d, _rn(base), off),
            A.encode_stur_xt_xn_imm(d, base, off))


def gen_memreg(rng, free):
    """The register-OFFSET access forms, whose offset register is a base reg.

    These are the forms a list blob past 32760 bytes needs, and the ones whose
    base the model once hardwired to SP. The offset register is `OFF_REG`, whose
    value the pool keeps small; a base plus a random 64-bit offset is not an
    address this harness can let the CPU touch.
    """
    base = _base(rng)
    off = OFF_REG
    d = _dst(rng, free)
    if rng.random() < 0.5:
        return ("ldr x%d, [%s, x%d]" % (d, _rn(base), off),
                A.encode_ldr_xt_xn_xm(d, base, off))
    return ("str x%d, [%s, x%d]" % (d, _rn(base), off),
            A.encode_str_xt_xn_xm(d, base, off))


#: The mixes, and what each one is for. `MIXES` is a NAME → generators map
#: rather than one generator list because a mix is also a row in
#: `bugs/FORMAL_model_fuzz_ledger.md`, and a row that cannot be named cannot be
#: written down.
#:
#: Two forms are deliberately NOT here, and both absences are recorded rather
#: than left to be discovered as a coverage gap:
#:
#:   * The SP write-back pairs (STP pre-index, LDP post-index). SP is where this
#:     harness anchors its comparison window, so an instruction that moves it
#:     moves the anchor: measured, 28 SIGBUS/SIGSEGV cases in a 297-case sweep,
#:     every one of them the harness's fault and none of them a fact about
#:     `arm64_step`. `arm64_step` has arms for both (0xa9800000, 0xa8c00000) and
#:     they are untested here.
#:   * `LDP Xd1, Xd2, [SP, #imm]` (signed offset, 0xa9400000), which the model
#:     DOES step. No encoder in `formal/arm64.py` emits it and that is now a
#:     decision with a reason rather than an accident: the encoder that claimed
#:     it under that name encoded a single-register load off a REGISTER base
#:     with its two arguments swapped and its offset in EIGHTIES, so a caller
#:     that used it would have got a proof about one instruction (the model's
#:     0xa9400000 arm) and an image containing another. It was deleted rather
#:     than repaired, because nothing wants the instruction — frame traffic is
#:     the writeback pairs above and a single SP-relative word is
#:     `encode_ldr_xt_sp_imm` — and a correct encoder no lowering calls is a
#:     table entry rather than an instruction any image can contain. So this
#:     absence is permanent until a lowering wants the form, and the byte-exact
#:     `ldp`/`stp` cases in `test_arm64_encoders.py` are what would catch it if
#:     one landed wrong.
MIXES = {
    "alu": (gen_alu, gen_moves),
    "flags": (gen_flags, gen_alu),
    "shifts": (gen_shifts, gen_alu),
    "muldiv": (gen_muldiv, gen_alu),
    "select": (gen_select, gen_flags),
    "ext": (gen_ext, gen_alu),
    "mem": (gen_mem, gen_alu),
    "memreg": (gen_memreg, gen_mem),
}


def free_regs():
    return [r for r in range(31) if r not in ADDR_REGS and r != OFF_REG]


def subs_flags(a, b):
    """`arm64_subs_flags a b`, in Python, for picking a case's starting NZCV."""
    diff = (a - b) & ((1 << 64) - 1)
    n = diff >> 63
    z = 1 if diff == 0 else 0
    c = 1 if a >= b else 0
    v = ((a ^ b) & (a ^ diff)) >> 63
    return n | (z << 1) | (c << 2) | (v << 3)


#: Operand pairs for each NZCV a subtraction can produce, so a case can be given
#: the flags it needs instead of whatever a random draw happens to make. N=1
#: with Z=1 is not producible by ANY subtraction — a zero result has no sign —
#: and that is an architectural fact about the flag, not a gap in the table.
_SUBS_SEEDS = {}
for _a in (0, 1, 2, 3, 5, 7, 0x7FFFFFFFFFFFFFFF, 0x8000000000000000,
           0xFFFFFFFFFFFFFFFF, 0xFFFFFFFF00000000, 0x100000000):
    for _b in (0, 1, 2, 3, 5, 7, 0x7FFFFFFFFFFFFFFF, 0x8000000000000000,
               0xFFFFFFFFFFFFFFFF, 0xFFFFFFFF00000000, 0x100000000):
        _SUBS_SEEDS.setdefault(subs_flags(_a, _b), []).append((_a, _b))
SEEDABLE_NZCV = tuple(sorted(_SUBS_SEEDS))


def gen_flagseed(rng, free):
    """The first instruction of every case: a `cmp` that SETS the flags.

    It has to exist, and it has to be a real instruction, because the model's
    initial NZCV is a constant while the hardware's on entry to the generated
    function is whatever the C driver last computed — `MSR NZCV` cannot make
    them equal (see the note above), and nothing else can. So the case's first
    instruction establishes them, on both sides, and every flag-reading
    instruction in the case is downstream of that.

    Which flags it establishes is CHOSEN rather than drawn: the NZCV the model
    starts the case with is a function of the operand values, and those are
    searched so that a sweep covers every reachable flag combination instead of
    the handful a uniform draw produces.
    """
    t = rng.choice(SEEDABLE_NZCV)
    a, b = rng.choice(_SUBS_SEEDS[t])
    rn, rm = _r(rng, free), _r(rng, free)
    if rng.random() < 0.5:
        return "cmp x%d, x%d" % (rn, rm), A.encode_cmp_xn_xm(rn, rm)
    imm = rng.choice((0, 1, 8, 16, 0x7FF))
    return "cmp x%d, #%d" % (rn, imm), A.encode_cmp_xn_imm(rn, imm)


def gen_case(rng, mix, length=None):
    """One case: a random state and a short random instruction sequence.

    The register values are drawn from a MIXTURE of shapes rather than uniformly
    at random, because the disagreements that matter live at the boundaries: a
    uniform 64-bit draw almost never produces an operand whose bit 63 is set and
    bit 0 clear, which is where a shift, a divide, a signed compare and a sign
    extension each behave differently from the case next to it. So every case
    gets one value of each interesting shape (all-ones, one-hot at the top, the
    sign boundary, a small count, a shift amount that is a multiple of the width,
    ...) placed at random, and the rest uniformly at random.
    """
    free = free_regs()
    gens = MIXES[mix]
    n = length if length is not None else rng.randrange(2, MAX_INSNS + 1)
    shape = interesting_word(rng)
    regs = []
    for i in range(31):
        if rng.random() < 0.45:
            regs.append(rng.getrandbits(64))
        else:
            regs.append(shape(rng))
    for r in ADDR_REGS:
        regs[r] = MODEL_SP + rng.randrange(0, MEM_A)
    # The register-OFFSET access forms add this register's value to the base's,
    # and every other register holds a random 64-bit value, so this one is
    # reserved to hold a small offset. Without it the pool asks the CPU for an
    # address 2**64 bytes away and gets SIGSEGV, which is a fact about the pool
    # and not about the model.
    regs[OFF_REG] = rng.randrange(0, MEM_NEG + 1)
    texts, words = [], []
    text, word = gen_flagseed(rng, free)
    texts.append(text)
    words.append(struct.unpack("<I", word)[0])
    for _ in range(n - 1):
        text, word = rng.choice(gens)(rng, free)
        texts.append(text)
        words.append(struct.unpack("<I", word)[0])
    mem = bytes(rng.randrange(256) for _ in range(MEM_HI - MEM_LO))
    return Case(regs, rng.randrange(16), mem, texts, words)


def interesting_word(rng):
    """One 64-bit value from a shape list, as a function of the seed."""
    kind = rng.randrange(12)
    if kind == 0:
        return lambda r: 0
    if kind == 1:
        return lambda r: (1 << 64) - 1
    if kind == 2:
        return lambda r: 1 << 63
    if kind == 3:
        return lambda r: (1 << 63) - 1
    if kind == 4:
        return lambda r: 1 << r.randrange(64)
    if kind == 5:
        return lambda r: r.randrange(1, 256)
    if kind == 6:
        return lambda r: r.randrange(64)
    if kind == 7:
        # a short run of high bits, e.g. 3 << 60 — masked, because
        # `7 << 63` is 2^65 and `struct.pack("<Q", …)` would refuse it.
        return lambda r: (r.randrange(1, 8) << r.randrange(3, 61)) & ((1 << 64) - 1)
    if kind == 8:
        return lambda r: 0xFFFFFFFF00000000 | r.getrandbits(32)
    if kind == 9:
        return lambda r: r.getrandbits(32)
    if kind == 10:
        return lambda r: ((r.getrandbits(32) << 32) | r.getrandbits(32)) & ((1 << 64) - 1)
    return lambda r: r.getrandbits(64)

# ── the assembler cross-check ───────────────────────────────────────────
#
# The bytes both engines execute are the ASSEMBLER's, never ours. `formal/
# arm64.py`'s encoding is only used to decide what the instruction IS, and a
# disagreement with `as -arch arm64` is reported as `ENC-MISMATCH` — a bug in
# the encoder table, which is a real bug but not a bug in `arm64_step`, and the
# two must not be reported as one thing. Without this line the harness cannot
# tell an encoder that emits a different instruction from a model that steps a
# real one wrongly, and it would spend its whole finding budget on the first.
def assemble(texts, workdir):
    """`[asm_text]` → `[4 bytes each]`, or None where `as` refused.

    One `as` invocation for the whole batch, and the bytes come back out of
    `otool -s` in ADDRESS order, which is what makes them comparable with
    `struct.pack("<I", word)` from `formal/arm64.py`. The label lines between
    the instructions are there so a refusal names WHICH instruction was refused
    rather than the whole file, and they cost no bytes: every instruction is
    four bytes and every label is four-aligned, so instruction `k` is bytes
    `[4k, 4k+4)` — which the total-length assertion below checks rather than
    assumes, because an assumption here would silently mis-pair every encoding
    in the run.
    """
    src = os.path.join(workdir, "insns.s")
    obj = os.path.join(workdir, "insns.o")
    with open(src, "w") as f:
        f.write(".text\n")
        for i, text in enumerate(texts):
            f.write("%s\n.globl _mark_%d\n_mark_%d:\n" % (text, i, i))
    r = subprocess.run(["as", "-arch", "arm64", "-o", obj, src],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return [None] * len(texts), r.stderr.strip()
    out = subprocess.run(["otool", "-s", "__TEXT", "__text", obj],
                         capture_output=True, text=True).stdout
    hexed = "".join("".join(l.split()[1:]) for l in out.splitlines()[2:] if l.strip())
    raw = bytes.fromhex(hexed)
    if len(raw) != 4 * len(texts):
        return [None] * len(texts), (
            "assembled %d bytes for %d instruction(s): the label-per-"
            "instruction layout is not 4 bytes each" % (len(raw), len(texts)))
    # `otool -s` prints each word in DISPLAY order, which is the reverse of the
    # memory order; the bytes have to be flipped back before they can be
    # compared with what `struct.pack("<I", word)` produced.
    return [raw[4 * i:4 * i + 4][::-1] for i in range(len(texts))], None


# ── the native harness ──────────────────────────────────────────────────
#
# One function per case, generated. Every case's instructions are emitted as
# TEXT, so the same `clang` that links the harness assembles them: the hardware
# cannot run anything we invented, only what the assembler accepted.
C_DRIVER = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include <signal.h>
#include <sys/mman.h>

#define NCASE %(n)d
#define MEM_LO %(mem_lo)d
#define MEM_HI %(mem_hi)d
#define MODEL_SP %(sp)d
#define DUMP_OFF %(dump)d
#define STASH %(stash)d

typedef struct { uint64_t regs[32]; uint8_t nzcv; uint8_t pad[7];
                 uint8_t mem[MEM_HI - MEM_LO]; } CaseIn;

static uint64_t _tab[33];
static sigjmp_buf _jb;

/* A Mach-O C symbol `foo` is the object symbol `_foo`, and an assembler label
   is used verbatim, so the definition below says `__case_i` where this file
   says `_case_i`. Nothing else in either file has to care. */
extern void _case_0(uint64_t *tab);
%(externs)s
static void (*const _fns[NCASE])(uint64_t *) = { %(fns)s };

static volatile sig_atomic_t _signo = 0;
static void on_fault(int sig) { _signo = sig; siglongjmp(_jb, 1); }

static const char *signame(int s) {
    switch (s) {
    case SIGILL: return "SIGILL";
    case SIGSEGV: return "SIGSEGV";
    case SIGBUS: return "SIGBUS";
    case SIGFPE: return "SIGFPE";
    case SIGTRAP: return "SIGTRAP";
    default: return "SIGNAL";
    }
}

int main(int argc, char **argv) {
    if (argc != 2) { fprintf(stderr, "usage: %%s CASES\n", argv[0]); return 2; }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror("open"); return 2; }
    unsigned char *region = mmap(NULL, 8192, PROT_READ | PROT_WRITE,
                                 MAP_PRIVATE | MAP_ANON, -1, 0);
    if (region == MAP_FAILED) { perror("mmap"); return 2; }
    unsigned char *win = region + 128;
    memset(region, 0, 8192);
    /* SA_ONSTACK matters here: a case runs with SP inside the mmap'd window,
       so the kernel's signal frame — which goes BELOW SP — has barely any room,
       and a handler that faults inside its own handler takes the whole run
       down instead of reporting one bad case. The alternate stack is the
       standard answer and costs one `sigaltstack`. */
    static char altstack[SIGSTKSZ * 4];
    stack_t ss;
    memset(&ss, 0, sizeof ss);
    ss.ss_sp = altstack;
    ss.ss_size = sizeof altstack;
    if (sigaltstack(&ss, NULL) != 0) { perror("sigaltstack"); return 2; }
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_fault;
    sa.sa_flags = SA_ONSTACK;
    sigaction(SIGILL, &sa, NULL);
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    sigaction(SIGFPE, &sa, NULL);
    sigaction(SIGTRAP, &sa, NULL);
    CaseIn in;
    for (int i = 0; i < NCASE; i++) {
        if (fread(&in, sizeof in, 1, f) != 1) {
            fprintf(stderr, "short input at case %%d\n", i); return 2;
        }
        /* SP is the window base, so every model address `MODEL_SP + off` is the
           hardware address `win + off`. */
        for (int r = 0; r < 31; r++) _tab[r] = in.regs[r];
        /* The pool hands every register over in MODEL coordinates; the three
           that name an address (SP and the two base registers) are re-based
           onto this run's window, and `win` is exactly one window. */
        for (int r = 0; r < 31; r++)
            if (r == 31 || r == %(a0)d || r == %(a1)d)
                _tab[r] = in.regs[r] - MODEL_SP + (uint64_t)(uintptr_t)win;
        _tab[31] = (uint64_t)(uintptr_t)win;
        _tab[32] = in.nzcv;
        memset(region, 0, 8192);
        /* Model coordinate `a` is hardware offset `a - MODEL_SP` from the
           window base, because the model's SP is the constant MODEL_SP and the
           hardware's SP is the window. */
        memcpy(win + MEM_LO - MODEL_SP, in.mem, MEM_HI - MEM_LO);
        int sig = 0;
        _signo = 0;
        fflush(stdout);
        if (sigsetjmp(_jb, 1) == 0) {
            _fns[i](_tab);
        } else {
            sig = _signo;
        }
        if (sig) {
            /* Which signal, and which case: a case that traps is a generator
               bug (an address outside the window, or an instruction the
               assembler accepted but the CPU rejects), never a model verdict. */
            printf("F %%d %%s\n", i, signame(sig));
            continue;
        }
        const uint64_t *d = (const uint64_t *)(win + DUMP_OFF);
        printf("H %%d", i);
        for (int r = 0; r < 32; r++) {
            /* The three registers that name an ADDRESS — SP and the two pool
               base registers — hold `window + off` where the model holds
               `MODEL_SP + off`, so they are translated back here, where `win`
               is known. Everything else is byte-identical on both sides, which
               is what makes the comparison a plain equality over 32 registers
               with no exception list in the checker. */
            unsigned long long v = (unsigned long long)d[r];
            if (r == 31 || r == %(a0)d || r == %(a1)d)
                v -= (unsigned long long)(uintptr_t)win - MODEL_SP;
            printf(" %%016llx", v);
        }
        printf(" %%llx %%llx %%llx", (unsigned long long)d[32], (unsigned long long)d[33],
               (unsigned long long)d[34]);
        /* The window is relative to the SP the case ENDED with, so a case that
           moves SP with a writeback is compared over the same bytes the model
           read and wrote rather than over whatever used to be there. */
        unsigned char *end = (unsigned char *)(uintptr_t)d[31];
        for (int b = MEM_LO; b < MEM_HI; b++)
            printf(" %%02x", end[b - MODEL_SP]);
        printf("\n");
    }
    fclose(f);
    return 0;
}
"""


def write_harness(cases, workdir):
    """The `.s` and the driver; returns (asm_path, c_path).

    Per case the generated function is the stub, then the case's instructions,
    then the epilogue — and `4:` sits on the case's first instruction while
    `2:` sits on the epilogue's, which is what lets the stub and the epilogue
    record BOTH pc values with two PC-relative `adr`s and no absolute address
    anywhere in the generated assembly. Only
    the DIFFERENCE between them is compared: the model knows its own pc as a
    compile-time constant and cannot know where the harness's code landed.
    """
    asm, externs, fns = [], [], []
    for i, case in enumerate(cases):
        body = "\n".join("    " + t for t in case.texts) + "\n"
        asm.append(
            "    .globl __case_%d\n"
            "    .p2align 2\n"
            "__case_%d:\n%s%s2:\n%s"
            % (i, i, STUB_HEAD, body, STUB_TAIL_BODY))
        externs.append("extern void _case_%d(uint64_t *tab);" % i)
        fns.append("_case_%d" % i)
    asm_path = os.path.join(workdir, "harness.s")
    with open(asm_path, "w") as f:
        f.write("// generated by tools/formal_model_fuzz.py -- do not edit\n")
        f.write("    .text\n")
        f.write("\n".join(asm))
    c_path = os.path.join(workdir, "harness.c")
    with open(c_path, "w") as f:
        f.write("// generated by tools/formal_model_fuzz.py -- do not edit\n")
        f.write(C_DRIVER % {"n": len(cases), "mem_lo": MEM_LO,
                            "mem_hi": MEM_HI, "dump": DUMP_OFF,
                            "stash": STASH_OFF, "sp": MODEL_SP,
                            "a0": ADDR_REGS[0], "a1": ADDR_REGS[1],
                            "externs": "\n".join(externs),
                            "fns": ", ".join(fns)})
    return asm_path, c_path


def run_native(cases, workdir, verbose=False):
    """Build and run the harness.

    `{i: ("OK", regs32, pc_end, pc_start, probe, mem)}`, or
    `{i: ("FAULT", signame)}` for a case the CPU refused to execute.
    """
    asm_path, c_path = write_harness(cases, workdir)
    exe = os.path.join(workdir, "harness")
    r = subprocess.run(["clang", "-arch", "arm64", "-O0", "-o", exe, c_path, asm_path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("clang failed:\n%s" % r.stderr[-4000:])
    data = os.path.join(workdir, "cases.bin")
    with open(data, "wb") as f:
        for case in cases:
            # 31 registers; the driver sets SP itself from the window base, so
            # the 32nd slot is written as 0 and never read.
            f.write(struct.pack("<32Q", *(list(case.regs[:31]) + [0])))
            f.write(struct.pack("<B7x", case.nzcv))
            f.write(case.mem)
    r = subprocess.run([exe, data], capture_output=True, text=True, timeout=600)
    if r.returncode != 0 and not r.stdout:
        raise RuntimeError("harness failed: %s" % (r.stderr[-2000:] or r.returncode))
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "F":
            out[int(parts[1])] = ("FAULT", parts[2])
            continue
        i = int(parts[1])
        try:
            vals = [int(v, 16) for v in parts[2:]]
        except ValueError:
            # A signal that arrived while the previous case's line was being
            # printed leaves a partial line behind; the case that faulted is
            # reported on the next line and this one has nothing usable in it.
            continue
        regs = vals[:32]
        # The dump band's own three words, in the order `C_DRIVER` prints them:
        # SLOT_PC_END, SLOT_PROBE, SLOT_PC_START.
        pc_end, probe, pc_start = vals[32], vals[33], vals[34]
        mem = bytes(vals[35:])
        out[i] = ("OK", regs, pc_end, pc_start, probe, mem)
    if verbose:
        sys.stderr.write("  native: %d case(s) reported\n" % len(out))
    return out


# ── the Lean model ──────────────────────────────────────────────────────
#
# One `#eval` per case, in ONE lean process (the whole point of batching: a
# per-case launch is 1.2 GB of Lean each). Each case is a structure literal, and
# the model runs `arm64_steps`, which is `arm64_go`'s one-step body — advance
# the pc when the step left it alone — applied `n` times. The memory is the
# window's bytes at `[MEM_LO, MEM_HI)` and 0 elsewhere, which is what the
# windowed comparison requires.
LEAN_HEAD = '''import ProofLib

def MODEL_PC : Nat := @PC@
def MODEL_SP : Nat := @SP@
def MEM_LO : Nat := @Mlo@
def MEM_HI : Nat := @Mhi@

structure Case where
  regs : List UInt64
  nzcv : UInt8
  mem : List UInt8
  code : List UInt8
  n : Nat

/-- The memory a case starts with: the window's bytes in window coordinates,
0 everywhere else, which is what the windowed comparison compares against. -/
def memOf (m : List UInt8) : Nat → UInt8 :=
  fun a => if MEM_LO <= a && a < MEM_HI then m.getD (a - MEM_LO) 0 else 0

/-- The case's code bytes, `0` before the first instruction. -/
def codeOf (c : List UInt8) : Nat → UInt8 :=
  fun a => if a < MODEL_PC then 0 else c.getD (a - MODEL_PC) 0

def stOf (c : Case) : Arm64State :=
  { x0 := c.regs.getD 0 0, x1 := c.regs.getD 1 0, x2 := c.regs.getD 2 0, x3 := c.regs.getD 3 0
    x4 := c.regs.getD 4 0, x5 := c.regs.getD 5 0, x6 := c.regs.getD 6 0, x7 := c.regs.getD 7 0
    x8 := c.regs.getD 8 0, x9 := c.regs.getD 9 0, x10 := c.regs.getD 10 0, x11 := c.regs.getD 11 0
    x12 := c.regs.getD 12 0, x13 := c.regs.getD 13 0, x14 := c.regs.getD 14 0, x15 := c.regs.getD 15 0
    x16 := c.regs.getD 16 0, x17 := c.regs.getD 17 0, x18 := c.regs.getD 18 0, x19 := c.regs.getD 19 0
    x20 := c.regs.getD 20 0, x21 := c.regs.getD 21 0, x22 := c.regs.getD 22 0, x23 := c.regs.getD 23 0
    x24 := c.regs.getD 24 0, x25 := c.regs.getD 25 0, x26 := c.regs.getD 26 0, x27 := c.regs.getD 27 0
    x28 := c.regs.getD 28 0, x29 := c.regs.getD 29 0, x30 := c.regs.getD 30 0
    sp := UInt64.ofNat MODEL_SP, pc := MODEL_PC, nzcv := c.nzcv, mem := memOf c.mem }

def HEX : List Char := "0123456789abcdef".toList

/-- 16 hex digits, always: a fixed width is what lets one `split` parse a line
of 34 of them without knowing which is which. -/
def hexNat (v : Nat) : String :=
  String.ofList ((List.range 16).reverse.map
    (fun i => HEX.getD (v / Nat.pow 16 i % 16) '0'))

/-- The compared window, relative to the SP the case ENDED with — see the
matching comment in `C_DRIVER`. A case that moves SP is therefore compared over
the bytes it actually touched. -/
def memHex (m : Nat → UInt8) (sp : Nat) : String :=
  String.ofList (List.flatten ((List.range (MEM_HI - MEM_LO)).map (fun k =>
    let b := (m (sp + MEM_LO - MODEL_SP + k)).toNat
    [HEX.getD (b / 16) '0', HEX.getD (b % 16) '0'])))

/-- The whole post-state as one line: 31 registers, SP, NZCV, the pc, and every
compared memory byte. -/
def render (c : Case) : String :=
  match arm64_steps (stOf c) (codeOf c.code) c.n with
  | none => "NORUN"
  | some s =>
      String.intercalate " "
        ((List.range 31).map (fun i => hexNat (arm64_reg i s).toNat)
          ++ [hexNat s.sp.toNat, hexNat s.nzcv.toNat, hexNat s.pc,
              memHex s.mem s.sp.toNat])
'''


def _u64(v):
    return "UInt64.ofNat 0x%x" % (v & ((1 << 64) - 1))


def write_lean(cases, workdir):
    # `@NAME@` rather than `%`-formatting: the header is Lean and contains `%`
    # as the modulo operator, which is a format-specifier in every other
    # language this file is written in.
    head = (LEAN_HEAD.replace("@PC@", str(MODEL_PC)).replace("@SP@", str(MODEL_SP))
            .replace("@Mlo@", str(MEM_LO)).replace("@Mhi@", str(MEM_HI)))
    out = [head]
    for i, case in enumerate(cases):
        regs = ", ".join(_u64(r if r not in ADDR_REGS else r) for r in case.regs[:31])
        code = "[" + ", ".join("0x%x" % b for w in case.words
                               for b in struct.pack("<I", w)) + "]"
        mem = "[" + ", ".join("0x%x" % b for b in case.mem) + "]"
        out.append("def case_%d : Case :=\n  { regs := [%s]\n"
                   "    nzcv := 0x%x\n    mem := %s\n    code := %s\n    n := %d }"
                   % (i, regs, case.nzcv, mem, code, case.n))
        out.append('#eval "%d " ++ render case_%d' % (i, i))
    path = os.path.join(workdir, "model.lean")
    with open(path, "w") as f:
        f.write("\n\n".join(out) + "\n")
    return path


def run_model(cases, workdir, verbose=False, chunk=25):
    """`{i: (regs31, sp, nzcv, pc_delta, mem) | None}` — None is a refusal.

    CHUNKED, and the chunk size is a bound rather than a convenience. Lean's
    elaborator keeps every `#eval`'s intermediate values alive for the life of
    the process, so one file with 300 `#eval`s is a materially different memory
    object from one with 25 — measured on this tree: the same 50 cases peaked
    above 8 GB in one process and 1.9 GB in four, with no difference in the
    cases. So the model's side runs in batches of `chunk` and nothing in this
    file's memory profile grows with `--cases`.
    """
    out = {}
    for start in range(0, len(cases), chunk):
        part = cases[start:start + chunk]
        sub = run_model_batch(part, workdir, verbose, start)
        out.update(sub)
    return out


def run_model_batch(cases, workdir, verbose=False, start=0):
    """One Lean process for `cases`, keyed by their index in the whole sweep."""
    path = write_lean(cases, workdir)
    lean = L.find_lean()
    if not lean:
        raise RuntimeError("lean not found (see ./lean-toolchain)")
    lib = os.path.join(ROOT, "lib")
    L.ensure_library(lean, lib)
    env = dict(os.environ)
    env["LEAN_PATH"] = lib
    r = L.run_lean(lean, [os.path.basename(path)], cwd=workdir, env=env,
                   wall_s=900.0, cpu_s=900.0, heartbeats=0)
    if r.exceeded:
        raise RuntimeError(r.exceeded)
    if r.returncode != 0:
        raise RuntimeError("lean failed:\n%s" % ((r.stderr or r.stdout or "")[-4000:]))
    out = {}
    for line in (r.stdout or "").splitlines():
        m = re.match(r'^"(\d+) (.*)"$', line.strip())
        if not m:
            continue
        i, body = start + int(m.group(1)), m.group(2)
        parts = body.split(" ")
        if len(parts) != 35 or len(parts[34]) != 2 * (MEM_HI - MEM_LO):
            out[i] = ("BAD", body)
            continue
        vals = [int(v, 16) for v in parts[:34]]
        hexmem = parts[34]
        mem = bytes(int(hexmem[j:j + 2], 16) for j in range(0, len(hexmem), 2))
        out[i] = ("OK", vals[:31], vals[31], vals[32], vals[33], mem)
    if verbose:
        sys.stderr.write("  model: %d case(s) evaluated\n" % len(out))
    return out


# ── the comparison ──────────────────────────────────────────────────────
FIELD_NAMES = ["x%d" % r for r in range(31)] + ["sp", "nzcv", "pc"]

#: X18 is EXCLUDED from the comparison, and this is a measurement rather than a
#: convenience. X18 is the register AArch64 reserves for platform use, and on
#: macOS something between the harness loading it and the epilogue dumping it
#: clobbers it: in a 600-case run, 36 cases ended with X18 = 0 on the hardware
#: where the model had a non-zero initial value, and EVERY ONE of them agrees
#: with the hardware when it is run on its own. Nothing in the generated stub
#: writes X18 after the table load — the case bodies never name it — so the
#: clobber is the platform's, and a register the platform owns is not a
#: register a differential harness can make a claim about. It is still DUMPED
#: (so the artefact is visible rather than invisible) and still reported when it
#: differs; it is just not counted as a disagreement.
SKIP_REGS = (18,)


def compare(hw, md):
    """The differences between the two engines' final states, as text lines.

    A plain equality on the registers, the flags, the pc DELTA and the whole
    window: the harness has already put the two base registers in model
    coordinates (see `C_DRIVER`), so there is nothing to translate here, and the
    only exception is `SKIP_REGS` — X18, which the platform owns and clobbers.
    """
    if hw[0] != "OK":
        return ["      hardware did not run: %s" % hw[1]]
    if md is None:
        return ["      arm64_step took no step"]
    if md[0] != "OK":
        return ["      lean said: %s" % md[1]]
    _t, hregs, hpc_end, hpc_start, hprobe, hmem = hw
    _t, mregs, msp, mnz, mpc, mmem = md
    # Each probe branch is TAKEN when its flag is SET, and a taken branch skips
    # the `add`, so the bits the probe accumulated are the flags that were
    # CLEAR. Inverting them gives the flags themselves.
    hnz = (~(hprobe - hregs[16])) & 0xF
    diffs = []
    pairs = list(zip(mregs, hregs)) + [(msp, hregs[31]), (mnz, hnz)]
    for k, (m, h) in enumerate(pairs):
        if k in SKIP_REGS:
            continue
        if m != h:
            diffs.append("      %-4s model=%016x hardware=%016x" % (FIELD_NAMES[k], m, h))
    if (mpc - MODEL_PC) != (hpc_end - hpc_start):
        diffs.append("      pc    model=+%d hardware=+%d"
                     % (mpc - MODEL_PC, hpc_end - hpc_start))
    if mmem != hmem:
        for b in range(MEM_HI - MEM_LO):
            if mmem[b] != hmem[b]:
                diffs.append("      mem[%+d] model=%02x hardware=%02x"
                             % (MEM_LO + b, mmem[b], hmem[b]))
    return diffs


# ── sweeps ──────────────────────────────────────────────────────────────
#
# A mix is a name, a corpus and a ledger row. The ledger is in
# `bugs/FORMAL_model_fuzz_ledger.md`: a tally is a fact about one run and stops
# being true the moment an instruction stops being generated, so what a sweep
# COVERED is written down beside what it found.
def build_cases(mix, count, seed, length=None):
    rng = random.Random("%s/%s" % (mix, seed))
    out = [gen_case(rng, mix, length) for _ in range(count)]
    for c in out:
        c.mix = mix
    return out


def all_cases(count, seed, mixes, length=None):
    out = []
    for mix in mixes:
        out.extend(build_cases(mix, max(1, count // len(mixes)), seed, length))
    return out


#: A64 has several mnemonics for one instruction, and `formal/arm64.py` and
#: `as` do not always pick the same one: `encode_mov_zr_xn` emits
#: `ADD Xd, Xn, #0` where the assembler emits `ORR Xd, XZR, Xn`, and both are
#: `MOV Xd, Xn`. A byte comparison reports that as a defect in the encoder
#: (60 of the 297 cases in the first 300-case sweep were that one fact), and a
#: disassembly comparison reports it for the same reason, so the disassembly is
#: put through this table first. Every entry is a pair of spellings the ARM ARM
#: defines as the same instruction; an entry that is not obviously one is not
#: added, because the table's whole job is to stop this check crying wolf.
_ALIASES = (
    (re.compile(r"^add (x\d+|sp), (x\d+|sp), #0x0$"), r"mov \1, \2"),
    (re.compile(r"^orr (x\d+|sp), xzr, (x\d+|sp)$"), r"mov \1, \2"),
    (re.compile(r"^orr (w\d+), wzr, (w\d+)$"), r"mov \1, \2"),
    (re.compile(r"^sub (x\d+|sp), xzr, (x\d+)$"), r"neg \1, \2"),
    (re.compile(r"^movz (x\d+), #0x0$"), r"mov \1, #0"),
    (re.compile(r"^subs xzr, (x\d+|sp), (x\d+|sp)$"), r"cmp \1, \2"),
)


def canonical_mnemonic(text):
    for pat, repl in _ALIASES:
        if pat.match(text):
            return pat.sub(repl, text)
    return text


def disassemble(words, workdir, tag):
    """`[word]` → `[mnemonic text]`, one per word, or None if `as` refused."""
    src = os.path.join(workdir, "dis-%s.s" % tag)
    obj = os.path.join(workdir, "dis-%s.o" % tag)
    with open(src, "w") as f:
        f.write(".text\n")
        for w in words:
            f.write(".inst 0x%08x\n" % w)
    r = subprocess.run(["as", "-arch", "arm64", "-o", obj, src],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = subprocess.run(["otool", "-tv", obj], capture_output=True,
                         text=True).stdout
    got = []
    for line in out.splitlines():
        # `otool -tv` prints address, mnemonic, operands — the mnemonic is part
        # of the comparison, because two encodings of one instruction can
        # differ in the operand SPELLING alone (`movz w0` vs `movz x0`) and
        # that difference is the finding.
        m = re.match(r"^([0-9a-f]{8,16})\s+(\S+)\s+(.*)$", line)
        if m:
            text = re.sub(r"\s+", " ", (m.group(2) + " " + m.group(3)).strip())
            got.append(canonical_mnemonic(text))
    return got


def resolve_words(cases, workdir):
    """Replace each case's words with the ASSEMBLER's; report real disagreements.

    "Real" is doing work here. `formal/arm64.py` encodes some instructions in a
    DIFFERENT but equivalent word than `as` chooses — `encode_mov_zr_xn` emits
    `ADD Xd, Xn, #0` where the assembler emits `ORR Xd, XZR, Xn` — and comparing
    bytes would report every such instruction as a defect, which is how a tool
    like this spends its whole finding budget on a non-finding. So the check is
    DISASSEMBLY equality: the two words must be the same instruction, and
    whether they are the same WORD is not the question.

    Returns `(mismatches, refused)`, where `refused` maps a case index to the
    instruction texts `as` rejected. A refusal is a bug in the POOL (an
    immediate outside the instruction's range, most often) and not in the model,
    so it is counted separately, the case is excluded from the comparison, and
    the harness substitutes `nop` there — one bad draw must not cost the other
    499 cases.
    """
    texts = [t for c in cases for t in c.texts]
    ours = [w for c in cases for w in c.words]
    got, err = assemble(texts, workdir)
    if got is None:
        raise RuntimeError("as failed:\n%s" % err)
    asm_words = [0 if b is None else struct.unpack("<I", b)[0] for b in got]
    mn_asm = disassemble(asm_words, workdir, "asm")
    mn_ours = disassemble(ours, workdir, "ours")
    if mn_asm is None or mn_ours is None or len(mn_asm) != len(texts) \
            or len(mn_ours) != len(texts):
        raise RuntimeError("could not disassemble the two encodings to compare "
                           "them; an ENC-MISMATCH would be unverifiable")
    bad, refused, k = [], {}, 0
    for ci, case in enumerate(cases):
        for j in range(case.n):
            if got[k] is None:
                refused.setdefault(ci, []).append(case.texts[j])
                case.texts[j] = "nop"
                case.words[j] = 0      # the model still gets `n` steps of bytes
                k += 1
                continue
            if mn_ours[k] != mn_asm[k]:
                bad.append((ci, case.texts[j],
                            "0x%08x %s" % (ours[k], mn_ours[k]),
                            "0x%08x %s" % (asm_words[k], mn_asm[k])))
            case.words[j] = asm_words[k]
            k += 1
    return bad, refused


def sweep(cases, workdir, verbose=False, lean_chunk=25):
    """One run: assemble-check, hardware, model, compare. → `(tally, findings)`."""
    bad_enc, refused = resolve_words(cases, workdir)
    hw = run_native(cases, workdir, verbose)
    md = run_model(cases, workdir, verbose, lean_chunk)
    tally = collections.Counter()
    findings = []
    for i, case in enumerate(cases):
        if i in refused:
            tally["ENC-FAIL"] += 1
            findings.append((i, case, ["as refused: %s" % t for t in refused[i]]))
            continue
        if i not in hw:
            tally["NO-REPORT"] += 1
            findings.append((i, case, ["the harness reported nothing for this case"]))
            continue
        if hw[i][0] == "FAULT":
            tally["FAULT"] += 1
            findings.append((i, case, ["hardware took %s" % hw[i][1]]))
            continue
        model = md.get(i)
        if model is None:
            tally["NO-EVAL"] += 1
            findings.append((i, case, ["lean printed nothing for this case"]))
            continue
        if model[0] != "OK":
            tally["NOSTEP"] += 1
            findings.append((i, case, ["arm64_step: %s" % model[1]]))
            continue
        diffs = compare(hw[i], model)
        if diffs:
            tally["WRONG"] += 1
            findings.append((i, case, diffs))
        else:
            tally["AGREE"] += 1
    for ci, text, ours, theirs in bad_enc:
        tally["ENC-MISMATCH"] += 1
        findings.append((ci, cases[ci],
                         ["our encoder says %s, `as -arch arm64` says %s, for: %s"
                          % (ours, theirs, text)]))
    return tally, findings


def report(tally, findings, cases, limit=12):
    print("arm64 model vs hardware: x18 skipped (platform register): " + "  ".join(
        "%s %d" % (k, tally[k]) for k in
        ("AGREE", "WRONG", "NOSTEP", "FAULT", "ENC-MISMATCH", "ENC-FAIL",
         "NO-REPORT", "NO-EVAL")
        if tally[k]) + "  (of %d)" % len(cases))
    for i, case, diffs in findings[:limit]:
        print("  case %d%s:" % (i, (" [%s]" % case.mix) if hasattr(case, "mix") else ""))
        for d in diffs[:10]:
            print(d)
        if len(diffs) > 10:
            print("      ... and %d more" % (len(diffs) - 10))
        if verbose_report:
            print(case.describe())
    if len(findings) > limit:
        print("  ... and %d more finding(s)" % (len(findings) - limit))


# ── minimisation ────────────────────────────────────────────────────────
#
# A 6-instruction disagreement is a finding; a 1-instruction disagreement is a
# test case. This is delta debugging over the instruction list, and it keeps the
# STATE fixed so the reduction cannot wander into a different bug: a shorter
# sequence that still disagrees is the same disagreement.
def verdict(case, workdir):
    """The case's verdict class, or None when it agrees."""
    tally, _findings = sweep([case], workdir)
    for name in ("WRONG", "NOSTEP", "FAULT", "ENC-MISMATCH"):
        if tally[name]:
            return name
    return None


def still_fails(case, workdir, want):
    """Whether `case` still fails the SAME WAY.

    "The same way" is load-bearing: without it the reduction deletes the
    instruction that disagrees and lands on a case that fails for a different
    reason (a refusal, say), and then reports a counterexample for an
    instruction that was never involved.
    """
    return verdict(case, workdir) == want


def minimise(case, workdir):
    """`case` reduced to the fewest instructions that still disagree.

    Instruction 0 is never removed, and that is not a shortcut: it is the case's
    flag seed (see `gen_flagseed`), so a reduction that dropped it would leave
    the two engines comparing NZCV values they never agreed on in the first
    place — the model starts from a constant and the hardware from whatever the
    C driver last computed. The reduction then reports a flags disagreement for
    every instruction it is asked about, including the ones that are innocent.
    """
    want = verdict(case, workdir)
    if want is None:
        raise ValueError("minimise: the case agrees, so there is nothing to "
                         "reduce")
    best = case
    changed = True
    while changed and best.n > 1:
        changed = False
        for j in range(1, best.n):
            trial = Case(best.regs, best.nzcv, best.mem,
                         best.texts[:j] + best.texts[j + 1:],
                         best.words[:j] + best.words[j + 1:])
            if still_fails(trial, workdir, want):
                best, changed = trial, True
                break
    return best


# ── main ────────────────────────────────────────────────────────────────
def main(argv):
    global verbose_report
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", type=int, default=CASES_PER_MIX * len(MIXES))
    ap.add_argument("--seed", default="model-fuzz")
    ap.add_argument("--mix", action="append", choices=sorted(MIXES))
    ap.add_argument("--length", type=int, default=None,
                    help="instructions per case (default: random 1..%d)"
                         % MAX_INSNS)
    ap.add_argument("--minimise", type=int, default=0, metavar="N",
                    help="reduce the first N wrong/refused cases to a "
                         "one-instruction case and print them")
    ap.add_argument("--work", default=None, help="artifact directory (default: a temp dir)")
    ap.add_argument("--keep", action="store_true", help="do not delete the artifacts")
    ap.add_argument("--lean-chunk", type=int, default=25, metavar="N",
                    help="cases per lean process (default 25; see run_model)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    verbose_report = args.verbose
    mixes = args.mix or sorted(MIXES)
    work = args.work or tempfile.mkdtemp(prefix="fmwork-")
    os.makedirs(work, exist_ok=True)
    try:
        cases = all_cases(args.cases, args.seed, mixes, args.length)
        tally, findings = sweep(cases, work, args.verbose, args.lean_chunk)
        report(tally, findings, cases)
        if args.minimise and findings:
            print("minimising %d finding(s):" % min(args.minimise, len(findings)))
            for i, case, _diffs in findings[:args.minimise]:
                small = minimise(case, work)
                print("  case %d reduces to:" % i)
                print(small.describe())
                d2 = sweep([small], work)[1]
                for _j, _c, dd in d2:
                    for line in dd[:6]:
                        print(line)
        return 0 if (tally["WRONG"] == 0 and tally["NOSTEP"] == 0
                     and tally["FAULT"] == 0 and tally["ENC-MISMATCH"] == 0
                     and tally["ENC-FAIL"] == 0 and tally["NO-REPORT"] == 0
                     and tally["NO-EVAL"] == 0) else 1
    finally:
        if not args.keep and not args.work:
            shutil.rmtree(work, ignore_errors=True)


verbose_report = False

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
