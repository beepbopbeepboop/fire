#!/usr/bin/env python3
"""Audit arm64 instruction coverage in the formal backend against real code.

The question this answers is "what can't the codegen emit, weighted by how
often a compiler actually emits it". Counting what a hand-written encoder
table contains is not the same question: a backend can have 52 encoders and
still be unable to express every conditional branch, which is the single
biggest thing a code generator needs.

Method:

  1. Take the encoder inventory from `formal/arm64.py` — everything named
     `encode_*` is something the backend CAN emit.
  2. Take the real instruction mix by disassembling the system binaries
     (`otool -tv /bin/*`). That is ground truth for "what a compiler emits on
     this target", independent of what we happen to implement.
  3. Map both onto base mnemonics, because an encoder is usually one base
     with variants (`add_xd_xn_imm` and `add_xd_xn_xm` are both `add`).
  4. Rank the uncovered mnemonics by how often they appear.

Deliberately EXCLUDED from the gap list, and why — a gap that is a decision
rather than an oversight:

  * `pacibsp` / `retab` / `paciza` / `autibsp` / `braa*` — roughly 18k of the
    real mix. These are Apple pointer-authentication, required on arm64e and
    conventional on Apple arm64. The formal backend emits a plain frame and
    has nothing to authenticate, so "supporting" them would mean generating
    instructions whose entire purpose is to be checked. Listed separately so
    the exclusion is visible rather than hidden in a filter.
  * `udf` — permanently-undefined, emitted by the assembler into padding and
    jump tables. Not an instruction we would ever want to generate.
  * `nop`, `hint`, `barrier`-class — no-ops and fences; a backend that has
    nothing to order has no use for them.

Usage:
    python3 tools/arm64_insn_audit.py                # full report
    python3 tools/arm64_insn_audit.py --top 40
    python3 tools/arm64_insn_audit.py --binaries /bin/ls /bin/cat
"""
import argparse
import collections
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ARM64 = os.path.join(REPO, "formal", "arm64.py")

# Base mnemonics an encoder family provides. An encoder whose name starts with
# one of these counts as covering that base.
FAMILIES = (
    "adrp", "adr", "ldr", "ldur", "str", "stur", "ldp", "stp", "ldrsw", "ldrsb",
    "ldrsh", "ldrb", "ldrh", "strb", "strh", "b", "cbz", "cbnz", "tbz", "tbnz",
    "br",
    "bl", "ret", "svc", "mov", "movz", "movk", "movn", "mvn", "nop", "add",
    "sub", "subs", "adc", "sbc", "mul", "madd", "msub", "smull", "umull",
    "smulh", "umulh", "neg", "negs", "cmp", "cmn", "tst", "ccmp", "ccmn",
    "csel", "cset", "csinc", "csinv", "csneg", "cinc", "csinv", "and", "orr",
    "eor", "eon", "bic", "orn", "sxtb", "sxth", "sxtw", "uxtb", "uxth",
    "lsl", "lsr", "asr", "lslv", "lsrv", "asrv", "sdiv", "udiv", "ror", "extr", "sbfx",
    "ubfx", "bfi", "bfxil", "ubfiz", "sbfiz", "ldrsw", "ccmp", "csel",
    # our own private helpers, not architectural mnemonics
    "_emit", "movz", "bl", "br",
)

# Kept for completeness but not scored as a gap; see the module docstring.
EXCLUDED = {
    "pacibsp", "paciza", "autibsp", "autiza", "retab", "braa", "braaz",
    "blraa", "blraaz", "udf", "nop", "hlt", "dmb", "dsb", "isb", "yield",
    "wfe", "wfi", "sev", "sevl", "hint", "pacia", "autib", "pacib",
}


def encoder_bases(path=ARM64):
    """Base mnemonics the backend can emit, from `formal/arm64.py`."""
    src = open(path).read()
    names = re.findall(r"^def (encode_[A-Za-z0-9_]+)", src, re.M)
    bases = set()
    for n in names:
        n = n[len("encode_"):]
        for fam in sorted(FAMILIES, key=len, reverse=True):
            if n == fam or n.startswith(fam + "_"):
                bases.add(fam)
                break
        else:
            bases.add(n)
    return bases, len(names)


def binary_mix(binaries):
    """{mnemonic: count} over the disassembly of `binaries`."""
    counts = collections.Counter()
    for b in binaries:
        try:
            out = subprocess.run(["otool", "-tv", b], capture_output=True,
                                 text=True, timeout=300).stdout
        except Exception:
            continue
        for line in out.splitlines():
            if not re.match(r"^[0-9a-f]{8,}", line):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            mn = parts[1].strip().split(" ")[0]
            if mn:
                counts[mn] += 1
    return counts


def default_binaries():
    out = []
    for d in ("/bin", "/usr/bin"):
        try:
            out += [os.path.join(d, f) for f in sorted(os.listdir(d))]
        except OSError:
            pass
    return [b for b in out if os.path.isfile(b) and not os.path.islink(b)][:200]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--binaries", nargs="*", default=None)
    args = ap.parse_args()

    bins = args.binaries or default_binaries()
    bases, n_enc = encoder_bases()
    mix = binary_mix(bins)

    total = sum(mix.values())
    covered = sum(c for m, c in mix.items() if m in bases)
    excluded = sum(c for m, c in mix.items() if m in EXCLUDED)

    print(f"encoders in formal/arm64.py : {n_enc} "
          f"({len(bases)} base mnemonics)")
    print(f"disassembled               : {total} instructions over "
          f"{len(mix)} distinct mnemonics, {len(bins)} binaries")
    print(f"covered by an encoder      : {covered} "
          f"({100.0 * covered / max(1, total):.1f}%)")
    print(f"excluded by decision       : {excluded} "
          f"(pointer auth, udf, hints — see docstring)")
    print(f"genuinely uncovered        : {total - covered - excluded} "
          f"({100.0 * (total - covered - excluded) / max(1, total):.1f}%)")

    def covers(mn):
        """Does any encoder family cover this mnemonic?

        The part before the "." matters: `b.ne`, `b.eq` and `b.le` are one
        instruction (B.cond) with the condition in the mnemonic, so matching
        whole strings reports every conditional branch as a gap when B.cond
        was implemented — which is precisely the gap worth noticing, so it
        must not be a false one."""
        if mn in bases:
            return True
        head = mn.split(".")[0]
        return head in bases

    gaps = [(c, m) for m, c in mix.items()
            if not covers(m) and m not in EXCLUDED]
    gaps.sort(reverse=True)
    print(f"\ntop {args.top} uncovered, by how often a compiler emits them:")
    for c, m in gaps[:args.top]:
        print(f"  {c:8d}  {100.0 * c / max(1, total):5.2f}%  {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
