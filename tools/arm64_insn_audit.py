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

  * **An encoder no lowering emits** — and this exclusion is the tool's second
    method step, because it is the same mistake as the pointer-auth one and it
    was invisible until it was looked for. `bugs/FORMAL_arm64_instruction_coverage.md`
    records the lesson at its sharpest: `Assembler.resolve()` had no `B.cond`
    case, so `imm19` stayed 0, every conditional branch pointed at itself, and a
    fully green byte-exact encoder suite coexisted with a compiler that hung on
    any false comparison. An encoder with no CALLER is that failure one step
    earlier: the bytes are provably right and the instruction cannot occur in
    any image. Counting those as covered is how a survey reports 92% when the
    difference between that and the truth is a table nobody calls, so
    `encoder_bases` reports only the encoders a lowering in `formal/` actually
    references, and the ones nothing references are PRINTED by name — the same
    rule the pointer-auth exclusion follows, and for the same reason: an
    exclusion hidden in a filter is dishonest accounting.

    Measured on this tree, 2026-10-03: 14 of 75 encoders are referenced nowhere
    outside their own definition (`blr`, `movn`, `csinc`, `csinv`, `csneg`,
    `tbz`, `tbnz`, `subs`, `cmn`, `tst`, `strh`, the SP-relative `ldr`/`str`,
    the SP `ldp`, and a 32-bit `cset`). Four of those are instructions the
    survey's own write-up says were "wired at every site" — `CSINC`, `CSINV`,
    `CSNEG`, `TBZ` and `TBNZ` — so the write-up was reading the encoder table
    where it should have read the callers, which is the mistake this step exists
    to make impossible to repeat.

    That measurement is a dated one and the list is a MOVING one: an encoder
    leaves it the moment a lowering emits it, which is the ordinary order of
    work here. `blr` has — the call through a function VALUE emits
    `encode_blr_xn(16)` (`formal/arm64_codegen.py`, the `through_value` arm of a
    call), so `blr` is covered now and
    `bugs/FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md`
    records the move as this survey's own measurement rather than a change to it.
    Run the tool for the current number; nothing here states one that a
    lowering cannot invalidate.

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
    # `blr`, and the reason it is named explicitly rather than left to a prefix
    # rule: `encode_blr_xn` does not start with `bl_`, so with only `bl` in the
    # table its base came out as `blr_xn`, which matches no mnemonic a
    # disassembler ever prints — an encoder the backend HAS, reported as a gap.
    # Under-reporting coverage is the same defect as over-reporting it, and the
    # gap list is what somebody works through next.
    "blr",
    "ubfx", "bfi", "bfxil", "ubfiz", "sbfiz", "ldrsw", "ccmp", "csel",
    # IEEE-754 binary64, scalar: the arithmetic that has to reach the FP unit
    # for a `double` to round at all, the compare that decides CPython's
    # comparison semantics (which are NOT the integer ones, because an
    # unordered compare has its own flags), and the two conversions that no
    # arithmetic on the bit pattern can express.
    "fadd", "fsub", "fmul", "fdiv", "fneg", "fcmp", "fmov", "scvtf", "fcvtzs",
    # our own private helpers, not architectural mnemonics
    "_emit", "movz", "bl", "br",
)

# Kept for completeness but not scored as a gap; see the module docstring.
EXCLUDED = {
    "pacibsp", "paciza", "autibsp", "autiza", "retab", "braa", "braaz",
    "blraa", "blraaz", "udf", "nop", "hlt", "dmb", "dsb", "isb", "yield",
    "wfe", "wfi", "sev", "sevl", "hint", "pacia", "autib", "pacib",
}


def encoder_names(path=ARM64):
    """Every `encode_*` defined in `formal/arm64.py`, in file order."""
    src = open(path).read()
    return re.findall(r"^def (encode_[A-Za-z0-9_]+)", src, re.M)


def unwired_encoders(path=ARM64, roots=None):
    """The encoders no lowering REFERENCES — the ones an image can never contain.

    An encoder is wired when its name occurs somewhere in `formal/` other than
    its own `def` line: a call from `arm64_codegen.py`, a dispatch inside
    `arm64.py`, anything at all. That is a name search rather than a call-graph
    walk on purpose — it is the WEAKEST test that still separates "the table has
    it" from "something emits it", and a weaker test errs toward counting an
    encoder as wired, which is the direction that does not shrink coverage.

    `roots` is `formal/` by default and is a parameter so a test can ask the
    question of a smaller tree; the answer is a property of the repository, not
    of one file, which is why it is not a function of `path` alone.
    """
    roots = roots or [os.path.dirname(path)]
    blob = "\n".join(
        open(os.path.join(r, f)).read()
        for r in roots for f in sorted(os.listdir(r)) if f.endswith(".py"))
    out = []
    for n in encoder_names(path):
        # `\b`-delimited so `encode_add_xd_xn_imm` is not matched by a mention
        # of `encode_add_xd_xn`, and the def line itself is the one occurrence
        # every encoder starts with.
        if len(re.findall(r"\b" + re.escape(n) + r"\b", blob)) <= 1:
            out.append(n)
    return out


def base_of(name):
    """The base mnemonic one encoder covers, or the whole name when none does."""
    n = name[len("encode_"):]
    for fam in sorted(FAMILIES, key=len, reverse=True):
        if n == fam or n.startswith(fam + "_"):
            return fam
    return n


def encoder_bases(path=ARM64):
    """(covered bases, every base, n encoders, unwired encoder names).

    **The first element is the WIRES, not the table**, and the difference is the
    point: see the module docstring's second exclusion. The other three are
    returned beside it because a report that says "47 base mnemonics" without
    saying "of 58, and here are the 14 encoders nobody calls" is the dishonest
    accounting the docstring warns about, one level up.
    """
    names = encoder_names(path)
    unwired = set(unwired_encoders(path))
    bases, every = set(), set()
    for n in names:
        (bases if n not in unwired else set()).add(base_of(n))
        every.add(base_of(n))
    return bases, every, len(names), sorted(unwired)


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
    bases, every, n_enc, unwired = encoder_bases()
    mix = binary_mix(bins)

    # A base whose EVERY encoder is unwired is not covered, and its occurrences
    # are a decision (see the docstring) rather than a gap — so they go in the
    # excluded total, named below it. A base with one wired encoder among three
    # is covered, which is why this is computed from `every - bases` and not
    # from the unwired names directly.
    dead_bases = every - bases
    total = sum(mix.values())
    covered = sum(c for m, c in mix.items() if m in bases)
    excluded = sum(c for m, c in mix.items()
                   if m in EXCLUDED or m.split(".")[0] in dead_bases)

    print(f"encoders in formal/arm64.py : {n_enc} "
          f"({len(every)} base mnemonics)")
    print(f"emitted by a lowering       : {n_enc - len(unwired)} "
          f"({len(bases)} base mnemonics) — an encoder nothing CALLS is not "
          f"an instruction any image contains")
    print(f"disassembled               : {total} instructions over "
          f"{len(mix)} distinct mnemonics, {len(bins)} binaries")
    print(f"covered by an encoder      : {covered} "
          f"({100.0 * covered / max(1, total):.1f}%)")
    print(f"excluded by decision       : {excluded} "
          f"(pointer auth, udf, hints, and encoders with no caller — see "
          f"docstring)")
    print(f"genuinely uncovered        : {total - covered - excluded} "
          f"({100.0 * (total - covered - excluded) / max(1, total):.1f}%)")
    if unwired:
        print(f"\nencoders no lowering emits ({len(unwired)}), by name — "
              f"printed rather than filtered, because an exclusion nobody can "
              f"see is not one:")
        for n in unwired:
            print(f"  {n}  ({base_of(n)})")

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
