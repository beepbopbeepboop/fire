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
    # ── the logical/arithmetic right-shift and left-shift immediates ────
    #
    # These three are the ONLY encoders here whose immediate is a PAIR of
    # logical-immediate fields (immr and imms) inside a UBFM/SBFM word rather
    # than one unsigned bitfield, and they were consequently the only ones with
    # no coverage at all: `encode_lsl_xd_xn_imm` carried base `0xd3780000`
    # where the docstring said `0xd3400000`, which put `immr = 0b111000` in
    # bits 21:16 and made 56 of the 64 shift amounts encode to a different
    # instruction. A sample of 3 would have caught that and 3 was what would
    # have been written if this had been covered by a sample, so it is all 64.
    for sh in range(64):
        c.append((f"lsl x0, x1, #{sh}", A.encode_lsl_xd_xn_imm(0, 1, sh)))
        c.append((f"lsr x0, x1, #{sh}", A.encode_lsr_xd_xn_imm(0, 1, sh)))
        c.append((f"asr x0, x1, #{sh}", A.encode_asr_xd_xn_imm(0, 1, sh)))
    for xd, xn in ((30, 31), (3, 7), (17, 16)):
        for sh in (0, 1, 8, 12, 31, 63):
            c.append((f"lsl x{xd}, x{xn}, #{sh}",
                      A.encode_lsl_xd_xn_imm(xd, xn, sh)))
    # ── flag-setting ALU ───────────────────────────────────────────────
    for xn, xm in ((0, 1), (1, 0), (7, 31), (31, 31)):
        c.append((f"tst x{xn}, x{xm}", A.encode_tst_xn_xm(xn, xm)))
        c.append((f"cmn x{xn}, x{xm}", A.encode_cmn_xn_xm(xn, xm)))
        c.append((f"subs x2, x{xn}, x{xm}", A.encode_subs_xd_xn_xm(2, xn, xm)))
    return c


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

    try:
        test_range_is_enforced()
        passed += 1
    except TestFailure as e:
        failed += 1
        print(f"  FAIL {e}")

    print(f"\narm64 encoders vs `as -arch arm64`: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
