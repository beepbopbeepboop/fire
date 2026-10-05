#!/usr/bin/env python3
"""Differential test: our arm64 encoders vs the platform assembler.

Every encoder in `formal/arm64.py` is checked by assembling the SAME
instruction with `as -arch arm64` and comparing the bytes. That is a real
oracle rather than a hand-derived bit layout: a wrong base opcode or a field
in the wrong bit position shows up as a byte mismatch, not as a program that
happens to work on the one input you tried.

This is the same shape as the differential the gimple path gets from
`gimple_codegen`: one implementation is the reference and the other is
measured against it. Here the reference is Apple's assembler.

Skipped (not failed) where the host has no arm64 assembler, so the file is
still useful to run elsewhere — but a skip on an arm64 Mac means the encoders
are going unchecked, which is the case worth noticing.

Usage:
    python3 test_arm64_encoders.py [-v]
"""
import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from formal import arm64 as A  # noqa: E402


class TestFailure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise TestFailure(msg)


HAVE_AS = bool(shutil.which("as"))


def assemble(text, tmpdir):
    """The machine word for `text`, as an int, or None without an assembler.

    Read out of the object's __text with `otool -s` and decoded BIG-endian:
    that hex dump prints each word in display order, so decoding it
    little-endian yields the byteswapped instruction and every comparison then
    fails for the same uninteresting reason."""
    if not HAVE_AS:
        return None
    src = os.path.join(tmpdir, "probe.s")
    obj = os.path.join(tmpdir, "probe.o")
    with open(src, "w") as f:
        f.write(".text\n" + text + "\n")
    r = subprocess.run(["as", "-arch", "arm64", "-o", obj, src],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise TestFailure(f"assembler rejected {text!r}: {r.stderr.strip()}")
    out = subprocess.run(["otool", "-s", "__TEXT", "__text", obj],
                         capture_output=True, text=True).stdout
    hexed = "".join("".join(l.split()[1:])
                    for l in out.splitlines()[2:] if l.strip())
    raw = bytes.fromhex(hexed)
    check(len(raw) >= 4, f"no code emitted for {text!r}")
    return int.from_bytes(raw[:4], "big")


# (assembler text, our bytes). Each entry is one instruction; the test
# assembles the text and compares. Offsets are byte offsets as our encoders
# take them, and the assembler is given a matching `. +N` where relevant.
def cases():
    c = []
    # ── B.cond, every condition the codegen can ask for ────────────────
    for cond in ("eq", "ne", "cs", "cc", "mi", "pl", "vs", "vc",
                 "hi", "ls", "ge", "lt", "gt", "le"):
        c.append((f"b.{cond} .+8", A.encode_b_cond(cond, 8)))
        c.append((f"b.{cond} .-8", A.encode_b_cond(cond, -8)))
        c.append((f"b.{cond} .+1048572", A.encode_b_cond(cond, 1048572)))
        c.append((f"b.{cond} .-1048572", A.encode_b_cond(cond, -1048572)))
    # ── CSEL family ─────────────────────────────────────────────────────
    for enc, name in ((A.encode_csel_xd_xm_cond, "csel"),
                      (A.encode_csinc_xd_xm_cond, "csinc"),
                      (A.encode_csinv_xd_xm_cond, "csinv"),
                      (A.encode_csneg_xd_xm_cond, "csneg")):
        for (xd, xn, xm) in ((0, 1, 2), (5, 0, 31), (30, 31, 0),
                              (3, 7, 19)):
            for cond in ("eq", "ne", "lt", "ge", "hi", "lo"):
                c.append((f"{name} x{xd}, x{xn}, x{xm}, {cond}",
                          enc(xd, xn, xm, cond)))
    # ── TBZ / TBNZ ─────────────────────────────────────────────────────
    for bit in (0, 1, 5, 31):
        c.append((f"tbz x3, #{bit}, .+8", A.encode_tbz_xn_bit(bit, 3, 8)))
        c.append((f"tbnz x3, #{bit}, .+8", A.encode_tbnz_xn_bit(bit, 3, 8)))
    c.append(("tbz x3, #7, .-8", A.encode_tbz_xn_bit(7, 3, -8)))
    c.append(("tbnz x3, #7, .-8", A.encode_tbnz_xn_bit(7, 3, -8)))
    c.append(("tbz x3, #9, .+16384", A.encode_tbz_xn_bit(9, 3, 16384)))
    c.append(("tbnz x3, #9, .-16384", A.encode_tbnz_xn_bit(9, 3, -16384)))
    # ── LDUR / STUR ────────────────────────────────────────────────────
    for imm in (0, 8, -8, 255, -256, 7, -1):
        c.append((f"ldur x4, [x3, #{imm}]", A.encode_ldur_xt_xn_imm(4, 3, imm)))
        c.append((f"stur x4, [x3, #{imm}]", A.encode_stur_xt_xn_imm(4, 3, imm)))
    # ── MOVZ / MOVN / MOVK, every width and every halfword ───────────────
    #
    # This file had no `movz`, `movn` or `movk` case at all while those three
    # were among the most-called encoders in the backend (`movz` alone had 102
    # call sites), and that absence is the whole of how the following went
    # unnoticed:
    #
    #     encode_movz_xd_imm  base 0x52800000   ← 32-bit, named `_xd_`
    #     encode_movz_xn_imm  base 0xd2800000   ← 64-bit, named for a PARAMETER
    #     encode_movk_xd_imm  base 0xf2800000   ← 64-bit, and the name was right
    #
    # So the file named `_xd_` meant two different widths, and only the byte
    # comparison against `as` distinguishes them: with `imm16` capped at
    # `0xffff` the 32-bit and 64-bit forms leave the SAME value in the X
    # register, so no value-level test and no run of a compiled program can see
    # the difference. That is why both widths are swept here for every register
    # and every immediate, rather than one of them being sampled.
    #
    # `MOVN` has only the 32-bit encoder, and the asymmetry is the point: the
    # two `MOVZ` encoders are named for their widths now
    # (`encode_movz_xd_imm` / `encode_movz_wd_imm`) where they were one width
    # and one parameter name, and there is nothing to name a 64-bit `MOVN`
    # because nothing encodes one. `lib/ProofLib.lean`'s `arm64_step` does have
    # an arm for the 64-bit form (`0x92800000`) and that arm is unreachable
    # from any image this backend builds, which is the survey's "no encoder"
    # half rather than a hole in the model.
    for (d, i) in ((0, 0), (0, 1), (0, 0xffff), (5, 0x1234), (16, 0x8000),
                   (30, 0xffff)):
        c.append((f"movz x{d}, #{i}", A.encode_movz_xd_imm(d, i)))
        c.append((f"movz w{d}, #{i}", A.encode_movz_wd_imm(d, i)))
        c.append((f"movn w{d}, #{i}", A.encode_movn_wd_imm(d, i)))
        # Every `hw`, because MOVK's field is the halfword INDEX and a base
        # carrying stray bits in `hw` corrupts the INSERT POSITION while
        # leaving the register number right — the same failure mode as the
        # shift-encoder sweep below, and the reason all four are here.
        for pos in (0, 16, 32, 48):
            c.append((f"movk x{d}, #{i}, lsl #{pos}",
                      A.encode_movk_xd_imm(d, i, pos)))
    # ── the three pair-load/store forms, and the SP spellings ───────────
    # `ldp` was absent from this file entirely while the tree had an
    # `encode_ldp_xn_xt_sp` that emitted `ldp x0, x1, [x1, #16]` for the
    # arguments `(1, 0, 2)` — so both halves of that bug were invisible: no
    # caller, and no case. Every offset here is a multiple of 8 inside the
    # encodable range of a SIGNED 7-bit count of eighties (-512 .. 504), and
    # the register triples include `XZR` in each of the three roles, which is
    # what distinguishes `LDP`'s three fields from each other.
    for (t1, t2, rn, imm) in ((0, 1, 31, 16), (0, 1, 31, 0), (0, 1, 31, -8),
                              (0, 1, 31, 504), (0, 1, 31, -512), (3, 4, 31, 32),
                              (31, 1, 31, 16), (0, 31, 31, 16), (0, 1, 3, 24),
                              (5, 30, 30, 504)):
        base = "sp" if rn == 31 else f"x{rn}"
        c.append((f"ldp x{t1}, x{t2}, [{base}, #{imm}]",
                  A.encode_ldp_xt1_xt2_rn(t1, t2, rn, imm)))
    for (t1, t2, b) in ((0, 1, 16), (3, 4, 32), (30, 31, 8)):
        c.append((f"ldp x{t1}, x{t2}, [sp], #{b}",
                  A.encode_ldp_sp_post(t1, t2, b)))
        c.append((f"stp x{t1}, x{t2}, [sp, #-{b}]!",
                  A.encode_stp_sp_pre(t1, t2, b)))
    # ── the ADD/SUB immediate, and the SP spellings ──────────────────────
    # `x31` is not an assembly-language operand for ADD/SUB immediate (the
    # assembler reads that field as SP), so the SP forms get their own two
    # cases below rather than a register triple — and `sub sp, sp, #imm` is the
    # prologue's own stack decrement, so it is the spelling a bug here would
    # corrupt most visibly.
    for (d, n, i) in ((0, 0, 0), (0, 5, 8), (30, 30, 0xfff), (17, 16, 4095)):
        c.append((f"add x{d}, x{n}, #{i}", A.encode_add_xd_xn_imm(d, n, i)))
        c.append((f"sub x{d}, x{n}, #{i}", A.encode_sub_xd_xn_imm(d, n, i)))
    c.append(("add x16, sp, #0", A.encode_add_xd_xn_imm(16, 31, 0)))
    c.append(("add sp, sp, #16", A.encode_add_xd_xn_imm(31, 31, 16)))
    c.append(("sub sp, sp, #4032", A.encode_sub_xd_xn_imm(31, 31, 4032)))
    # ── other access widths ────────────────────────────────────────────
    for imm in (0, 2, 8, 40):
        c.append((f"ldrh w4, [x3, #{imm}]", A.encode_ldrh_wt_wn_imm(4, 3, imm)))
        c.append((f"strh w4, [x3, #{imm}]", A.encode_strh_wt_wn_imm(4, 3, imm)))
        c.append((f"ldrsh x4, [x3, #{imm}]", A.encode_ldrsh_xt_xn_imm(4, 3, imm)))
    for imm in (0, 4, 16):
        c.append((f"ldrsw x4, [x3, #{imm}]", A.encode_ldrsw_xt_xn_imm(4, 3, imm)))
    for imm in (0, 1, 9):
        c.append((f"ldrsb x4, [x3, #{imm}]", A.encode_ldrsb_xt_xn_imm(4, 3, imm)))
    # ── the shifted immediate form, which is what a large scratch offset
    # actually needs (131072 = 32 << 12) ─────────────────────────────────
    for imm12, sh in ((0, 0), (1, 0), (0xFFF, 0), (1, 1), (32, 1),
                      (0xFFF, 1)):
        scale = "" if sh == 0 else ", lsl #12"
        c.append((f"sub x9, x9, #{imm12}{scale}",
                  A.encode_sub_xd_xn_imm_sh(9, 9, imm12, sh)))
        c.append((f"add x0, x0, #{imm12}{scale}",
                  A.encode_add_xd_xn_imm_sh(0, 0, imm12, sh)))
    # ── flag-setting ALU ───────────────────────────────────────────────
    for xn, xm in ((0, 1), (1, 0), (7, 31), (31, 31)):
        c.append((f"tst x{xn}, x{xm}", A.encode_tst_xn_xm(xn, xm)))
        c.append((f"cmn x{xn}, x{xm}", A.encode_cmn_xn_xm(xn, xm)))
        c.append((f"subs x2, x{xn}, x{xm}", A.encode_subs_xd_xn_xm(2, xn, xm)))
    # ── the three immediate SHIFT encoders, every amount 0..63 ────────────
    #
    # Every one of these three is a UBFM/SBFM alias, so all three share a base
    # opcode and a pair of fields; a base that carries stray bits in `immr`
    # corrupts the shift AMOUNT while leaving `Rn`/`Rd` correct, which is why
    # the one broken encoder here was correct for a run of amounts and wrong
    # for every other one (`encode_lsl_xd_xn_imm` carried base `0xd3780000`
    # where its own docstring said `0xd3400000`: `1 << 12` returned `16`, and
    # only amounts 1-8 — the ones whose intended `immr` already had the stray
    # bits set — were right). Sweeping the whole 0..63 range per instruction is
    # what distinguishes that from a working encoder: no single amount picks it
    # out, and a hand-picked amount picks out one of the eight that were
    # already fine.
    #
    # Registered as a separate list so the sweep is one loop rather than three,
    # and so a new shift encoder is added here rather than left untested — this
    # file had no `lsl` case at all while `lsl` was the broken one.
    for enc, mn in ((A.encode_lsl_xd_xn_imm, "lsl"),
                    (A.encode_asr_xd_xn_imm, "asr"),
                    (A.encode_lsr_xd_xn_imm, "lsr")):
        for sh in range(64):
            c.append((f"{mn} x0, x0, #{sh}", enc(0, 0, sh)))
        # A non-zero Rd/Rn pair, so a field landing in the wrong bit position
        # cannot be masked by the all-zero operand the sweep above uses.
        for (xd, xn, sh) in ((5, 7, 12), (30, 31, 63), (1, 2, 33)):
            c.append((f"{mn} x{xd}, x{xn}, #{sh}", enc(xd, xn, sh)))
    # ── IEEE-754 binary64, scalar ────────────────────────────────────────
    #
    # Every operation over four register triples rather than one, because these
    # are three-field encodings whose fields sit in different places from the
    # integer ALU's: `fadd d0, d0, d1` and `fadd d0, d0, d1` differ in the
    # RESULT only, so a base word with `Rm` in `Rn`'s slot produces exactly
    # that instruction for every one of them and no single case sees it.
    #
    # The operand sets are chosen for what they are rather than for coverage:
    # (0, 0, 0) is the all-zero operand a misplaced field hides behind, (8, 9,
    # 10) is the high V-file triple where a field landing in bit 20..16 instead
    # of bit 4..0 becomes visible as a wrong register, and XZR (31) is what
    # makes `fmov d0, xzr` — the one-instruction `+0.0` — reachable at all.
    for (dd, dn, dm) in ((0, 0, 0), (0, 0, 1), (8, 9, 10), (2, 31, 30)):
        for enc, mn in ((A.encode_fadd_dd_dn_dm, "fadd"),
                        (A.encode_fsub_dd_dn_dm, "fsub"),
                        (A.encode_fmul_dd_dn_dm, "fmul"),
                        (A.encode_fdiv_dd_dn_dm, "fdiv")):
            c.append((f"{mn} d{dd}, d{dn}, d{dm}", enc(dd, dn, dm)))
        # The destination-aliases-a-source case: two-operand read-before-write
        # means `fadd d0, d0, d1` is the shape the emitter emits.
        c.append((f"fadd d{dd}, d{dd}, d{dm}",
                  A.encode_fadd_dd_dn_dm(dd, dd, dm)))
    for (dd, dn) in ((0, 1), (0, 0), (8, 9), (5, 31)):
        c.append((f"fneg d{dd}, d{dn}", A.encode_fneg_dd_dn(dd, dn)))
        c.append((f"fcmp d{dd}, d{dn}", A.encode_fcmp_dn_dm(dd, dn)))
    for (dd, xn) in ((0, 0), (0, 1), (0, 31), (8, 9), (7, 30)):
        c.append((f"fmov d{dd}, x{xn}", A.encode_fmov_gpr_to_v(dd, xn)))
    for (xd, dn) in ((0, 0), (0, 1), (31, 0), (9, 8), (30, 7)):
        c.append((f"fmov x{xd}, d{dn}", A.encode_fmov_v_to_gpr(xd, dn)))
    for (dn, xn) in ((0, 0), (0, 1), (8, 9), (1, 31)):
        c.append((f"scvtf d{dn}, x{xn}", A.encode_scvtf_dn_xn(dn, xn)))
    for (xd, dn) in ((0, 0), (0, 1), (9, 8), (30, 7)):
        c.append((f"fcvtzs x{xd}, d{dn}", A.encode_fcvtzs_xn_dn(xd, dn)))
    # ── MOVZ / MOVK / MOVN, BOTH widths, every field non-zero ─────────────
    #
    # **This file had no `movz`, `movk` or `movn` case at all**, so the three
    # most-used immediate encoders in the backend were the three it did not
    # mention, and one of them was misnamed: `encode_movz_xd_imm` emitted
    # `0x52800000` — `sf = 0`, so `movz wD` — under a name that says `xd`.
    # Nothing caught it because 103 call sites all pass an immediate under 2^16,
    # for which the 32- and 64-bit forms produce the same value; the defect was
    # in the NAME, and a name is only checkable against the assembler's word for
    # the text a reader would expect that name to mean. Hence both widths here
    # under both names.
    #
    # Swept rather than sampled, because the thing that was wrong is a single
    # bit — `sf` in bit 31 — and any one case that happened to use the width the
    # encoder emitted would pass. `movz x31` is NOT here: MOVZ's destination is
    # written and register 31 there is XZR, so `as` rejects the text outright
    # and the bound is asserted instead (`test_movz_cannot_write_xzr`).
    for imm in (0, 1, 0xff, 0x100, 0x5555, 0xffff):
        c.append((f"movz x0, #{imm}", A.encode_movz_xd_imm(0, imm)))
        c.append((f"movz w0, #{imm}", A.encode_movz_wd_imm(0, imm)))
        c.append((f"movn w0, #{imm}", A.encode_movn_wd_imm(0, imm)))
        for pos in (0, 16, 32, 48):
            lsl = "" if pos == 0 else f", lsl #{pos}"
            c.append((f"movk x0, #{imm}{lsl}",
                      A.encode_movk_xd_imm(0, imm, pos)))
    for (xd, imm) in ((1, 1), (5, 0x1234), (28, 0xffff), (30, 0x8000)):
        c.append((f"movz x{xd}, #{imm}", A.encode_movz_xd_imm(xd, imm)))
        c.append((f"movz w{xd}, #{imm}", A.encode_movz_wd_imm(xd, imm)))
        c.append((f"movn w{xd}, #{imm}", A.encode_movn_wd_imm(xd, imm)))
        c.append((f"movk x{xd}, #{imm}, lsl #32",
                  A.encode_movk_xd_imm(xd, imm, 32)))
    # ── the SP frame PAIRS, and the XZR slot a pair load may discard ──────
    #
    # `ldp` and `stp` are the whole of this backend's frame traffic
    # (`encode_stp_sp_pre` in a prologue, `encode_ldp_sp_post` in an epilogue),
    # and neither had a case in this file — which is how `encode_ldp_xn_xt_sp`
    # survived here at all: it claimed the `LDP [SP]` mnemonic, encoded a
    # single-register load off a register base with its two arguments swapped,
    # and shared nothing with the assembler but the base opcode. The pairs are
    # checked at both ends of their range and with `Rt2 = 31`, which the
    # architecture allows (the second load lands in XZR's slot and is
    # discarded) and which a `assert 0 <= rt2 <= 30` would have refused.
    for rt1, rt2 in ((0, 1), (0, 31), (1, 31), (30, 29)):
        for b in (8, 16, 64, 504):
            c.append((f"stp x{rt1}, x{rt2}, [sp, #-{b}]!",
                      A.encode_stp_sp_pre(rt1, rt2, b)))
        for b in (8, 16, 64, 504):
            c.append((f"ldp x{rt1}, x{rt2}, [sp], #{b}",
                      A.encode_ldp_sp_post(rt1, rt2, b)))
    # …and the STORE's far end, which the load cannot reach: imm7 is signed, so
    # -512 is representable and +512 is not (`as`: "range [-512, 504]").
    for b in (512,):
        c.append((f"stp x0, x1, [sp, #-{b}]!", A.encode_stp_sp_pre(0, 1, b)))
    # ── the integer core: the forms this file never mentioned ────────────
    #
    # `tools/formal_isa_census.py` answers "which emitted form has no byte-for-
    # byte differential against `as`", and the answer on this tree was 40 of the
    # 77 encoders the emitters call — including every register-form ALU
    # operation, both un/aligned loads and stores, all four branches and both
    # shift-register forms. That is not a subtle hole: `encode_add_xd_xn_xm`
    # has 29 call sites and was checked by nothing, so a wrong field in it would
    # have reached every one of them with this file green.
    #
    # Every row below is a byte comparison, which is the only oracle that can
    # execute the instruction, and each sweeps the operand SHAPES rather than
    # one tuple: a register field landing in the wrong place is invisible when
    # every case writes register 0.
    for (xd, xn, xm) in ((0, 1, 2), (5, 7, 19), (30, 31, 0), (2, 0, 0)):
        c.append((f"add x{xd}, x{xn}, x{xm}", A.encode_add_xd_xn_xm(xd, xn, xm)))
        c.append((f"sub x{xd}, x{xn}, x{xm}", A.encode_sub_xd_xn_xm(xd, xn, xm)))
        c.append((f"mul x{xd}, x{xn}, x{xm}", A.encode_mul_xd_xn_xm(xd, xn, xm)))
        c.append((f"smulh x{xd}, x{xn}, x{xm}",
                  A.encode_smulh_xd_xn_xm(xd, xn, xm)))
        c.append((f"adds x{xd}, x{xn}, x{xm}",
                  A.encode_adds_xd_xn_xm(xd, xn, xm)))
        c.append((f"and x{xd}, x{xn}, x{xm}", A.encode_and_xd_xn_xm(xd, xn, xm)))
        c.append((f"orr x{xd}, x{xn}, x{xm}", A.encode_orr_xd_xn_xm(xd, xn, xm)))
        c.append((f"eor x{xd}, x{xn}, x{xm}", A.encode_eor_xd_xn_xm(xd, xn, xm)))
        c.append((f"sdiv x{xd}, x{xn}, x{xm}", A.encode_sdiv_xd_xn_xm(xd, xn, xm)))
        c.append((f"udiv x{xd}, x{xn}, x{xm}", A.encode_udiv_xd_xn_xm(xd, xn, xm)))
        c.append((f"lslv x{xd}, x{xn}, x{xm}", A.encode_lslv_xd_xn_xm(xd, xn, xm)))
        c.append((f"lsrv x{xd}, x{xn}, x{xm}", A.encode_lsrv_xd_xn_xm(xd, xn, xm)))
        c.append((f"asrv x{xd}, x{xn}, x{xm}", A.encode_asrv_xd_xn_xm(xd, xn, xm)))
    # The two SCALED register adds, which are the same class as the unscaled one
    # and were the two encoders the shift-field could have gone into.
    for (xd, xn, xm) in ((0, 1, 2), (5, 7, 19), (30, 31, 0)):
        c.append((f"add x{xd}, x{xn}, x{xm}, lsl #3",
                  A.encode_add_xd_xn_xm_lsl3(xd, xn, xm)))
        c.append((f"add x{xd}, x{xn}, x{xm}, lsl #4",
                  A.encode_add_xd_xn_xm_lsl4(xd, xn, xm)))
    # Two-operand forms, over the same triples: a `Rd` in `Rm`'s place is the
    # failure, and one case cannot see it.
    for (xd, xn) in ((0, 1), (5, 7), (2, 0), (0, 30)):
        c.append((f"neg x{xd}, x{xn}", A.encode_neg_xd_xn(xd, xn)))
        c.append((f"mvn x{xd}, x{xn}", A.encode_mvn_xd_xn(xd, xn)))
        c.append((f"sxtb w{xd}, w{xn}", A.encode_sxtb_wd_wn(xd, xn)))
        c.append((f"sxth w{xd}, w{xn}", A.encode_sxth_wd_wn(xd, xn)))
        c.append((f"sxtw x{xd}, w{xn}", A.encode_sxtw_xd_wn(xd, xn)))
        xa = (xd + 1) % 31
        xm = (xn + 1) % 31
        c.append((f"msub x{xd}, x{xn}, x{xm}, x{xa}",
                  A.encode_msub_xd_xn_xm_xa(xd, xn, xm, xa)))
    # …and register 31 as a SOURCE, which the row above leaves out because
    # `MVN`'s encoder bounds it: register 31 in a source field is the ZERO
    # register, so `neg x0, xzr` is a real spelling with a real encoding and it
    # is the row that finds an `Rm` field in the wrong place. (`mvn x0, xzr`
    # and `msub …, xzr` are refused by the encoders, which is right: `ORN`'s
    # `Rn` and `MSUB`'s `Ra` at 31 name XZR, and A64 gives `MSUB` with
    # `Ra = 31` the meaning of `MUL`.)
    c.append(("neg x0, xzr", A.encode_neg_xd_xn(0, 31)))
    # AND (immediate): the mask WIDTH is the third argument, so all three
    # canonical immediates are cases and not one sample of the family.
    for (xd, xn, w) in ((0, 1, 8), (0, 1, 16), (0, 1, 32), (5, 7, 32),
                        (30, 31, 8)):
        c.append((f"and x{xd}, x{xn}, #{(1 << w) - 1}",
                  A.encode_and_xd_xn_imm(xd, xn, w)))
    # The flag-setting compares, over register pairs that include XZR in the
    # first operand (`cmp xzr, x1` is a NEG and `cmp x31, x1` is the SUBS the
    # overflow check emits) and the immediate form's whole range.
    # `Rn = 31` in the shifted-register class is XZR, not SP (see the note
    # above `arm64_step`'s ADD branch, and `bugs/FORMAL_arm64_instruction_
    # coverage.md`'s extended-register section), which is what makes `cmp
    # x31, x1` the NEG the overflow check leans on. `Rm = 31` is refused by
    # the encoder and rightly so: `SUBS` with `Rm = 31` is `SUB Xd, Rn, XZR`,
    # which the assembler spells `sub` and the backend does not emit.
    for (xn, xm) in ((0, 1), (1, 0), (31, 1), (31, 30)):
        c.append((f"cmp x{xn}, x{xm}", A.encode_cmp_xn_xm(xn, xm)))
    for (xn, imm) in ((0, 0), (0, 4095), (17, 8)):
        c.append((f"cmp x{xn}, #{imm}", A.encode_cmp_xn_imm(xn, imm)))
    # `Rn = 31` in the immediate class is SP (`cmp sp, #8`), which is the only
    # way a frame-pointer compare is spelled — and `as` refuses the `x31`
    # spelling outright, so the case has to use it.
    c.append(("cmp sp, #8", A.encode_cmp_xn_imm(31, 8)))
    c.append(("cmp sp, #0", A.encode_cmp_xn_imm(31, 0)))
    # CSEL's one-operand sibling, over EVERY condition: it is 72 call sites'
    # worth of boolean materialisation and a wrong condition field is a branch
    # that reads the wrong flags.
    for cond in ("eq", "ne", "cs", "cc", "mi", "pl", "vs", "vc",
                 "hi", "ls", "ge", "lt", "gt", "le"):
        c.append((f"cset x0, {cond}", A.encode_cset_xd_cond(0, cond)))
        c.append((f"cset x17, {cond}", A.encode_cset_xd_cond(17, cond)))
    # The unconditional branches. `encode_b`/`encode_bl` take the offset in
    # FOUR-BYTE UNITS (imm26 counts words, and their own docstrings say so)
    # while every other branch encoder here takes bytes, so the assembler text
    # is `.+32` and `.+8` respectively for the same jump — a difference that is
    # easy to read as a bug in one of the two and is not.
    for words in (8, -8, 262143, -262143):
        c.append((f"b .+{words * 4}", A.encode_b(words)))
        c.append((f"bl .+{words * 4}", A.encode_bl(words)))
    for (xn, off) in ((0, 8), (17, -8), (31, 4), (5, 0x80000)):
        c.append((f"cbz x{xn}, .+{off}", A.encode_cbz_xn(off, xn)))
        c.append((f"cbnz x{xn}, .+{off}", A.encode_cbnz_xn(off, xn)))
    # ── memory: unsigned offset, register offset, and the narrow widths ──
    #
    # Both ends of the 12-bit scaled range are here because the encoder picks
    # the narrowest form at the call site and a case at one end says nothing
    # about the other; and `SP` is the base the frame traffic uses, where the
    # assembler rejects the `x31` spelling.
    for (xt, base, off) in ((0, 3, 8), (0, 3, 32760), (5, 31, 16),
                            (30, 31, 32760), (17, 3, 0)):
        rn = "sp" if base == 31 else "x%d" % base
        c.append((f"ldr x{xt}, [{rn}, #{off}]",
                  A.encode_ldr_xt_xn_imm(xt, base, off)))
        c.append((f"str x{xt}, [{rn}, #{off}]",
                  A.encode_str_xt_xn_imm(xt, base, off)))
    for (wt, base, off) in ((0, 3, 4), (0, 3, 16380), (9, 31, 4)):
        rn = "sp" if base == 31 else "x%d" % base
        c.append((f"ldr w{wt}, [{rn}, #{off}]",
                  A.encode_ldr_wt_wn_imm(wt, base, off)))
        c.append((f"str w{wt}, [{rn}, #{off}]",
                  A.encode_str_wt_wn_imm(wt, base, off)))
    for (wd, base, off) in ((0, 3, 0), (0, 3, 4095), (4, 31, 1)):
        rn = "sp" if base == 31 else "x%d" % base
        c.append((f"ldrb w{wd}, [{rn}, #{off}]",
                  A.encode_ldrb_wd_wn(wd, base, off)))
        c.append((f"strb w{wd}, [{rn}, #{off}]",
                  A.encode_strb_wd_wn(wd, base, off)))
    # The REGISTER-offset forms, whose offset register is a second operand
    # rather than an immediate: `SP` as the base is the shape a stack-indexed
    # blob reaches, and XZR as the OFFSET register is a legal spelling the
    # assembler accepts and the encoder must too.
    for (xt, base, xm) in ((0, 3, 4), (5, 31, 4), (30, 3, 31), (17, 31, 2)):
        rn = "sp" if base == 31 else "x%d" % base
        c.append((f"ldr x{xt}, [{rn}, x{xm}]",
                  A.encode_ldr_xt_xn_xm(xt, base, xm)))
        c.append((f"str x{xt}, [{rn}, x{xm}]",
                  A.encode_str_xt_xn_xm(xt, base, xm)))
    # ── ADRP, the linker's entry stub ────────────────────────────────────
    #
    # `as` takes a page offset as a plain number rather than a label (a
    # label-relative ADRP is a relocation and `as` refuses to encode it in a
    # bare object), so the operand here is the page offset the encoder takes.
    for (xd, page) in ((0, 0), (0, 0x1000), (16, 0x1000), (30, 0x2000),
                       (5, 0x80000000)):
        c.append((f"adrp x{xd}, {page}", A.encode_adrp(xd, page)))
    # ── BR, SVC, RET ─────────────────────────────────────────────────────
    c.append(("br x3", A.encode_br_xn(3)))
    c.append(("br x16", A.encode_br_xn(16)))
    for imm8 in (0, 1, 60, 255):
        c.append((f"svc #{imm8}", A.encode_svc(imm8)))
    c.append(("ret", A.encode_ret()))
    return c


def equivalent_cases():
    """`[(ours, their_text)]` for encoders `as` spells a DIFFERENT way.

    One of them, and the reason this list exists rather than a case in
    `cases()`: `encode_mov_zr_xn` emits `ADD Xd, Xn, #0` (83 call sites) where
    `as` spells the same instruction `ORR Xd, XZR, Xn`. Both are MOV, both are
    architecturally identical, and a byte-for-byte comparison would be testing
    the SPELLING CHOICE rather than the encoding — the same distinction
    `tools/formal_model_fuzz.py`'s `_ALIASES` table draws when it compares
    DISASSEMBLY instead of bytes.

    What is checked here is the weaker but real property: that our word
    disassembles to the assembler's own text for the same instruction. A field
    in the wrong place changes the disassembly, so this is not vacuous; what it
    does not check is that our word is the word `as` would have chosen.
    """
    return [(A.encode_mov_zr_xn(0, 1), "mov x0, x1"),
            (A.encode_mov_zr_xn(5, 31), "mov x5, sp"),
            (A.encode_mov_zr_xn(30, 0), "mov x30, x0")]


def disassemble(word_bytes, tmpdir, tag):
    """`mnemonic text` for one instruction word, or None without `as`."""
    src = os.path.join(tmpdir, "d-%s.s" % tag)
    obj = os.path.join(tmpdir, "d-%s.o" % tag)
    with open(src, "w") as f:
        f.write(".text\n\t.inst 0x%08x\n" % int.from_bytes(word_bytes, "little"))
    if subprocess.run(["as", "-arch", "arm64", "-o", obj, src],
                      capture_output=True).returncode != 0:
        return None
    out = subprocess.run(["otool", "-tv", obj], capture_output=True,
                         text=True).stdout
    for line in out.splitlines():
        m = re.match(r"^[0-9a-f]{8,16}\s+(\S+)\s+(.*)$", line)
        if m:
            return re.sub(r"\s+", " ", (m.group(1) + " " + m.group(2)).strip())
    return None


def test_our_spelling_is_the_assemblers_instruction():
    """The alias rows must be the SAME INSTRUCTION, not merely a difference.

    `equivalent_cases()` is where a byte comparison is impossible, so the check
    here is disassembly equality after the alias is normalised the way
    `tools/formal_model_fuzz.py::_ALIASES` normalises it: `add x0, x1, #0` and
    `orr x0, xzr, x1` are both `mov x0, x1`. Without the normalisation this
    test would fail on the alias it exists to describe; with it, it fails on a
    field in the wrong place.
    """
    aliases = (
        (re.compile(r"^add (x\d+|sp), (x\d+|sp), #0x0$"), r"mov \1, \2"),
        (re.compile(r"^add (w\d+), (w\d+), #0x0$"), r"mov \1, \2"),
        (re.compile(r"^orr (x\d+|sp), xzr, (x\d+|sp)$"), r"mov \1, \2"),
        (re.compile(r"^orr (w\d+), wzr, (w\d+)$"), r"mov \1, \2"),
    )
    if not HAVE_AS:
        return
    with tempfile.TemporaryDirectory() as tmp:
        for i, (ours, text) in enumerate(equivalent_cases()):
            got = disassemble(ours, tmp, "e%d" % i)
            for pat, repl in aliases:
                if got and pat.match(got):
                    got = pat.sub(repl, got)
                    break
            check(got == text,
                  f"our encoding disassembles to {got!r} where the assembler's "
                  f"own text for the same instruction is {text!r}")


def test_the_sp_pair_offset_is_bounded():
    """A frame offset past the signed imm7 field must RAISE, not wrap.

    imm7 is signed and scaled by 8, so +512 bytes is not representable and
    masking it into the field produces -512: the pair lands 1024 bytes from
    where the caller asked, the program runs to completion, and nothing says
    so. `as` refuses the text outright, which is the same fact stated by the
    only oracle that can execute the instruction.
    """
    for enc, args, why in ((A.encode_ldp_sp_post, (0, 1, 512), "load"),
                           (A.encode_stp_sp_pre, (0, 1, 520), "store"),
                           (A.encode_ldp_sp_post, (0, 1, 4), "unaligned")):
        try:
            enc(*args)
        except AssertionError:
            continue
        raise TestFailure(
            f"{enc.__name__} accepted an unrepresentable {why} offset "
            f"{args[-1]}, which the assembler rejects")


def test_movz_cannot_write_xzr():
    """Register 31 is a DESTINATION here, so it is XZR and not a register.

    An encoder that accepts a word the assembler will not produce is a defect
    waiting for its first caller, and MOVZ's destination bound used to be 31 —
    the reading being "any general register", which is what 31 is in a SOURCE
    field and not in a destination one. `as` says so itself: `movz x31, #1` is
    an error, not a MOVZ into a scratch register.
    """
    for enc, args in ((A.encode_movz_xd_imm, (31, 1)),
                      (A.encode_movz_wd_imm, (31, 1)),
                      (A.encode_movn_wd_imm, (31, 1)),
                      (A.encode_movk_xd_imm, (31, 1, 0))):
        try:
            enc(*args)
        except AssertionError:
            continue
        raise TestFailure(
            f"{enc.__name__} accepted XZR as a destination, which is not "
            f"writable; the word it returns cannot be assembled")


def test_range_is_enforced():
    """Out-of-range must RAISE, not wrap.

    A branch whose offset is silently truncated is a branch to the wrong
    address, which no value-level test catches — the program still runs, it
    just computes something else. So the bound is checked, not clamped."""
    try:
        A.encode_b_cond("eq", 1 << 21)
    except AssertionError:
        return
    raise TestFailure("encode_b_cond accepted an offset past its imm19 range")


def test_a_base_mnemonic_is_either_wired_or_named():
    """An encoder's NAME has to say which mnemonic it covers.

    `tools/arm64_insn_audit.py` maps an encoder to a base mnemonic by matching
    the longest `FAMILIES` prefix, and an encoder that matches none becomes its
    own base — a string no disassembler ever prints. `encode_blr_xn` matched
    neither `bl` nor `br`, so its base was `blr_xn`, `blr` was reported as a GAP
    the backend can in fact close, and the gap list is the thing somebody works
    through next. Under-reporting coverage is the same defect as
    over-reporting it, in the direction that hides a one-line fix.

    So: every `encode_*` maps to a declared family. `blr` is in the table now,
    and this test is what keeps the next one from being a silent gap — it does
    NOT require the encoder to be wired, because landing an encoder before its
    lowering is the ordinary order of work here (the `B.cond` case the survey
    records is the encoder arriving first and the RELOCATION not following it).
    That is a different failure with a different test
    (`test_arm64_emission.py` asserts that no branch resolves to its own
    address).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "arm64_insn_audit", os.path.join(HERE, "tools", "arm64_insn_audit.py"))
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    unmapped = [n for n in audit.encoder_names()
                if audit.base_of(n) == n[len("encode_"):]
                and n[len("encode_"):] not in audit.FAMILIES]
    check(not unmapped,
          f"these encoders map to no declared base mnemonic, so every "
          f"mnemonic they cover is reported as a gap by the survey: "
          f"{unmapped}. Add the mnemonic to FAMILIES (or, if the name is not "
          f"a mnemonic plus operands, rename the encoder)")


def test_the_survey_does_not_count_an_encoder_nothing_emits():
    """The survey's headline number must be about IMAGES, not about the table.

    `bugs/FORMAL_arm64_instruction_coverage.md`'s own lesson is that byte-exact
    encoders are not instructions: `Assembler.resolve()` had no `B.cond` case,
    every conditional branch pointed at itself, and the whole encoder suite was
    green. An encoder with no caller is that one step earlier — the bytes are
    provably right and the instruction cannot occur in any image — and counting
    those as coverage is how a survey reports 92% when 15 of the 75 encoders
    are a table nobody calls.

    The assertion is the DIRECTION, not a number: the bases the audit calls
    covered must all come from an encoder some lowering references, and the
    ones nothing references must be printed by name rather than dropped in a
    filter. Pinning the exact set here would make this test a maintenance tax on
    every encoder that lands before its lowering, which is the ordinary order of
    work; pinning the direction makes it impossible for the number to go back to
    reading the table. **Which is also why no encoder is named below** — `blr`
    was the named example until the call through a function value emitted it,
    and a name is a claim about which encoders have no caller, so it goes stale
    the moment a lowering lands rather than when the survey is wrong.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "arm64_insn_audit", os.path.join(HERE, "tools", "arm64_insn_audit.py"))
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    covered, every, n_enc, unwired = audit.encoder_bases()
    check(unwired == sorted(audit.unwired_encoders()),
          "encoder_bases and unwired_encoders disagree about which encoders no "
          "lowering emits, so the report and its own helper can tell two "
          "different stories")
    check(covered <= every,
          f"the covered bases are not a subset of the bases in the table: "
          f"{sorted(covered - every)}")
    dead = every - covered
    # A base is uncovered EXACTLY when EVERY encoder for it is unwired, and the
    # "every" is the half that is easy to get wrong: `cset`, `ldr`, `str` and
    # `ldp` each have an unwired encoder here AND a wired one (the register
    # forms), so their base is covered. Stated as the two sets agreeing, which
    # is `encoder_bases`'s definition rather than a measurement of it — pinned
    # because a definition can be edited, and an `encoder_bases` that covered a
    # base because one encoder with that name happens to be unwired is the same
    # defect one level down: a report that cannot be reproduced from the two
    # sets it prints.
    explained = {audit.base_of(n) for n in unwired} - covered
    check(dead == explained,
          "the uncovered bases are not the bases ALL of whose encoders are "
          f"unwired, so the two halves of the report disagree: reported "
          f"uncovered {sorted(dead)}, explained by {sorted(explained)}")
    # The direction, as a statement about the SURVEY and not about any one
    # encoder: if every base reads as covered then `covered == every`, and a
    # survey that reports every mnemonic it can encode as an instruction one
    # real image contains is reading the table. This is the assertion the
    # named example used to carry, and it is deliberately NOT a named example
    # any more.
    #
    # It WAS `blr`, from the day the survey stopped reading the table, and it
    # stopped being an example on its own: the call through a function VALUE
    # (`formal/arm64_codegen.py`, the `through_value` arm of a call) emits
    # `encode_blr_xn(16)`, so `blr` moved from "encoded, never emitted" to
    # emitted and the pin went stale rather than wrong —
    # `bugs/FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md`
    # records the move as this survey's own measurement. A pin that names an
    # encoder is a claim that that encoder has no caller, and it is a claim
    # about the ORDER WORK LANDS IN: every lowering that arrives before the
    # survey is re-run flips one. The direction survives all of them.
    check(dead,
          "every base mnemonic reads as covered, so encoder_bases is reporting "
          "the TABLE rather than the callers: an encoder no lowering emits is "
          "not an instruction any image can contain, and a survey that cannot "
          f"say so of even one of the {len(unwired)} unwired encoders "
          f"({unwired}) has stopped measuring images")
    # …and one name for the OTHER direction, which is about a real lowering and
    # not about the audit: every conditional branch emits `B.cond`.
    check("b" in covered,
          "B.cond is emitted by every conditional branch and must stay covered")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if not HAVE_AS:
        print("SKIP: no `as` on PATH, cannot differential-test the encoders")
        return 0

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for text, ours in cases():
            try:
                ref = assemble(text, tmp)
                got = int.from_bytes(ours, "little")   # ours is packed LE
                if ref != got:
                    raise TestFailure(
                        f"{text}: ours {got:#010x} != as {ref:#010x}")
                passed += 1
                if args.verbose:
                    print(f"  ok   {text}")
            except TestFailure as e:
                failed += 1
                print(f"  FAIL {e}")
            except Exception as e:
                failed += 1
                print(f"  ERROR {text}: {type(e).__name__}: {e}")

    for name, fn in (("our alias spelling is the same instruction",
                      test_our_spelling_is_the_assemblers_instruction),
                     ("out-of-range raises", test_range_is_enforced),
                     ("movz cannot write XZR", test_movz_cannot_write_xzr),
                     ("the SP pair offset is bounded",
                      test_the_sp_pair_offset_is_bounded),
                     ("every encoder names a base mnemonic",
                      test_a_base_mnemonic_is_either_wired_or_named),
                     ("the survey counts emitted encoders, not table entries",
                      test_the_survey_does_not_count_an_encoder_nothing_emits)):
        try:
            fn()
            passed += 1
        except TestFailure as e:
            failed += 1
            print(f"  FAIL {name}: {e}")

    print(f"\narm64 encoders vs `as -arch arm64`: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
