#!/usr/bin/env python3
"""The peephole pass: a proof-carrying rewriter over the emitted instruction list.

`formal/arm64_codegen.py` and `formal/x86_64_codegen.py` emit straightforward
code — every value is copied, every immediate is materialized, every frame
slot is stored and reloaded — because the emitters have one job, which is to
be readable enough to prove. This module is the other job: a window-by-window
rewriter over the emitted bytes that removes the sequences the emitters
produce and nothing else.

**Every rule here is licensed by a theorem.** A rule is a `Rule` naming the
Lean statement in `lib/Peephole.lean` that says the rewrite leaves the machine
model's registers, flags and memory as it found them, under stated side
conditions. `unlicensed_rules()` reads the Lean source and reports any rule
whose theorem is not declared there, and `Arm64Codegen`/`X86_64Codegen`
refuse to run the pass while that list is non-empty: a rewrite without a proof
is not in this pass, which is the whole point of shipping one. The rules are
listed in `RULES`; the proofs are in `lib/Peephole.lean`; a test
(`test_formal_peephole.py::TestRulesAreLicensed`) keeps the two in step.

**The pass is off by default** (`--opt`). It shrinks the text, which means
every label, relocation, external-symbol stub and recorded pc has to move with
it — see `_Remap`, which is the one piece of this module that is not about
recognising instructions and is therefore the one most worth reading. Being
off by default also means the shipped toolchain's bytes are unchanged until
the corpus says otherwise, and `--opt` is how you ask to see the difference.

**Side conditions are part of a rule, not a comment on one.** A rule that
fires only when nothing reads a register states that condition in
`side_conditions` and discharges it in its matcher; the Lean theorem is
stated with the matching hypothesis. A rule whose soundness depends on a
condition this pass cannot decide does not exist here.
"""
import collections
import os
import struct
from dataclasses import dataclass

from formal.model import CodegenError

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEAN_PEEPHOLE = os.path.join(ROOT, "lib", "Peephole.lean")

# The window a rule may look at. 2 is every rule in the table; a longer window
# means a rule that reasons about a value's whole live range, which is a
# different kind of analysis and belongs in its own pass with its own proof.
WINDOW = 2


# ── arm64 decoding ──────────────────────────────────────────────────────────
@dataclass
class ArmInsn:
    """One decoded arm64 instruction, over the fields the rules read.

    `form` names the encoding class; a word whose class this module does not
    decode is `None`, and no rule matches it. That is the safe direction: the
    alternative — guessing — is how a rewriter silently changes an instruction
    it did not understand.

    `add_imm` is this backend's MOVE-TO-REGISTER spelled as an addition.
    `formal/arm64.py`'s `encode_mov_zr_xn` emits a register copy as
    `ADD Xd, Xn, #0` (base `0x91000000`, the 64-bit `ADD (immediate)` class:
    `sf=1, op=0, S=0`), so the class carries BOTH the copies and the genuine
    additions — 499 of the 633 `ADD (immediate)` instructions in
    `formal/examples` add zero, which is where the peephole's wins are. A rule
    that needs a COPY tests `imm == 0` for itself.

    The form is not called `mov`, and that is a bug this module had once:
    `add x17, x17, #8` has the same class as `add x1, x0, #0`, so a
    self-copy rule keyed on the class name deleted `add x17, x17, #8` from
    `fact.mojo` and the program's answer changed from 0 to 2. `imm` is in the
    decoded record for exactly this reason.
    """
    form: str
    off: int = 0
    rd: int = 0
    rn: int = 0
    rm: int = 0
    imm: int = 0
    byte_off: int = 0

    @property
    def size(self) -> int:
        return 4


def decode_arm64(word: int) -> ArmInsn | None:
    """Decode the arm64 classes the peephole rules match, or `None`.

    The masks and the order are `lib/ProofLib.lean`'s `arm64_step` if-chain,
    which is the decode the machine model actually performs — so a word this
    recognises as `mov` is a word the model steps as a register copy, and a
    rule's Lean theorem is about the same instruction the pass rewrote. The
    `rd ≠ 31` / `rn ≠ 31` exclusions in `mov` are the model's own split:
    register 31 is SP in the model (`arm64_set_reg 31` writes `sp`) and the
    hardware reads `Rn = 31` as the ZERO register in this class, so a word
    naming 31 is exactly the case where the two readings could differ and
    this pass leaves it alone.
    """
    # ADD (immediate), 64-bit, flags NOT set — `encode_mov_zr_xn`'s word.
    #
    # `sh == 0` is required and is not decoration: `arm64_step`'s arm for this
    # class reads the operand as `imm12` ALONE and does not look at bit 22,
    # while the hardware scales the immediate by 4096 when `sh` is set. A rule
    # over a word the model and the hardware already disagree about proves
    # nothing about the binary, so this decoder refuses those words outright.
    if (word & 0xFF800000) == 0x91000000 and ((word >> 22) & 1) == 0:
        rd = word & 0x1F
        rn = (word >> 5) & 0x1F
        if rd == 31 or rn == 31:
            return None
        return ArmInsn("add_imm", rd=rd, rn=rn, imm=(word >> 10) & 0xFFF)
    return None


#: The register-read set of every arm64 class `arm64_step` decodes, keyed by
#: the same masks in the same order. `None` for a word no row matches means
#: "unknown", and `reads_arm64` turns that into EVERY register — the pass can
#: then only conclude that nothing is dead, which is the answer that keeps a
#: rewrite sound. A liveness check that is wrong in the permissive direction
#: is the one bug in a peephole pass that turns into a wrong answer rather
#: than a wrong instruction count.
_ARM64_READS = [
    (0xFFE00000, 0x2A00FA00, ("rn",)),        # ORR Xd, XZR, Xn
    (0xFFE00000, 0x8B000000, ("rn", "rm")),   # ADD Xd, Xn, Xm
    (0xFFE00000, 0xCB000000, ("rn", "rm")),   # SUB Xd, Xn, Xm
    (0xFFE07C00, 0x9B007C00, ("rn", "rm")),   # MUL
    (0xFFFFFC1F, 0xCB0003E0, ("rn",)),        # NEG
    (0xFFE00000, 0xEB000000, ("rn", "rm")),   # CMP Xn, Xm
    (0xFFE00000, 0x8A000000, ("rn", "rm")),   # AND
    (0xFFE00000, 0xCA000000, ("rn", "rm")),   # EOR
    (0xFF800000, 0x11000000, ("rn",)),        # ADD Wd, Wn, #imm
    (0xFF800000, 0x91000000, ("rn",)),        # ADD Xd, Xn, #imm
    (0xFF800000, 0x51000000, ("rn",)),        # SUB Wd, Wn, #imm
    (0xFF800000, 0xD1000000, ("rn",)),        # SUB Xd, Xn, #imm
    (0xFF800000, 0xF1000000, ("rn",)),        # CMP Xn, #imm
    # The four bit-test branches take `0x7F000000`, NOT `0xFFC00000`: their
    # displacement is imm19 at bits 23..5 and their register is Rt at bits 4..0,
    # so bits 31..24 are ALL a class test can keep. A mask reaching into the
    # displacement compares against a value only the zero-displacement word can
    # have, so every real `cbz x4, #12` missed its row and came out of
    # `reads_arm64` as "reads every register" — sound, and enough on its own to
    # silence every rule below a conditional branch. `Assembler.resolve` reads
    # the same four classes with the same mask, for the same reason.
    (0x7F000000, 0x34000000, ("rt",)),        # CBZ  (W or X)
    (0x7F000000, 0x35000000, ("rt",)),        # CBNZ (W or X)
    (0x7F000000, 0x36000000, ("rt",)),        # TBZ  (W or X)
    (0x7F000000, 0x37000000, ("rt",)),        # TBNZ (W or X)
    (0xFF000000, 0x54000000, ()),             # B.cond — reads the FLAGS
    (0xFC000000, 0x14000000, ()),             # B — reads no register
    (0xFFE00000, 0xF9400000, ("rn",)),        # LDR Xt, [Xn, #imm]
    (0xFFE00000, 0xB9000000, ("rn",)),        # STR Wt, [Xn, #imm]
    (0x9F000000, 0x90000000, ()),             # ADR / ADRP
    (0xFFC00000, 0xA9800000, ("rn",)),        # STP pre/post — WRITES rt, rt2
    (0xFFC00000, 0xA8C00000, ("rn",)),        # LDP pre/post — WRITES rt, rt2
    (0xFFE00000, 0x52800000, ()),             # MOVZ Wd
    (0xFFE00000, 0xD2800000, ()),             # MOVZ Xd
    (0xFFE00000, 0xAA000000, ("rn", "rm")),   # ORR
    (0xFF800000, 0xF2800000, ()),             # MOVK
    (0xFF800000, 0x72800000, ()),             # MOVN Wd
    (0xFFE00000, 0x12800000, ("rn",)),        # ADD Wd, Wn, #imm
    (0xFFE00000, 0x92800000, ("rn",)),        # ADDS
    (0xFFFF0FE0, 0x9A9F07E0, ("rn", "rm")),   # CSEL
    (0xFFE00000, 0xF9000000, ("rn",)),        # STR Xt, [Xn, #imm]
    (0xFFC00000, 0xA9400000, ("rn",)),        # LDP offset — WRITES rt, rt2
    (0xFFE0FC00, 0xAA200000, ()),             # CSET
    (0xFFFFFC1F, 0xD61F0000, ("rn",)),        # BR Xn
    (0xFFFFFC1F, 0xD65F0000, ("rn",)),        # RET — reads X30
    (0xFFE0001F, 0xD4000001, ()),             # SVC
    (0xFFE0FC00, 0x13001C00, ("rn",)),        # SXTB
    (0xFFE0FC00, 0x13003C00, ("rn",)),        # SXTH
    (0xFFE0FC00, 0x93407C00, ("rn", "rm")),   # SDIV
    (0xFFC0FC00, 0x92401C00, ("rn", "rm")),   # LSLV
    (0xFFC0FC00, 0x92403C00, ("rn", "rm")),   # LSRV
    (0xFFC0FC00, 0x92407C00, ("rn", "rm")),   # ASRV
    (0xFFE0FC00, 0x9AC00800, ("rn", "rm")),   # UDIV
    (0xFFC0FC00, 0x9AC00C00, ("rn", "rm")),   # LSL
    (0xFFC0FC00, 0x9AC02000, ("rn", "rm")),   # LSR
    (0xFFC0FC00, 0x9AC02400, ("rn", "rm")),   # ASR
    (0xFFC0FC00, 0x9AC02800, ("rn", "rm")),   # ROR
    (0xFFE08000, 0x9B008000, ("rn", "rm")),   # MSUB
    (0xFFC0FC00, 0xD340FC00, ("rn",)),        # UBFM
    (0xFFC0FC00, 0x9340FC00, ("rn",)),        # SBFM
    (0xFFC00000, 0xD3400000, ("rn",)),        # UBFX
    (0xFFD00000, 0x39400000, ("rn",)),        # LDRB
    (0xFFD00000, 0x39000000, ("rn",)),        # STRB
    (0xFFD00000, 0x79400000, ("rn",)),        # LDRH
    (0xFFD00000, 0x79000000, ("rn",)),        # STRH
    (0xFFD00000, 0x39800000, ("rn",)),        # LDRSB
    (0xFFD00000, 0x79800000, ("rn",)),        # LDRSH
    (0xFFD00000, 0xB9800000, ("rn",)),        # LDRSW
    (0xFFD00000, 0xB9400000, ("rn",)),        # LDR Wt
    (0xFFE0FC00, 0xF8606800, ("rn", "rm")),   # LDR Xt, [Xn, Xm]
    (0xFFE0FC00, 0xF8206800, ("rn", "rm")),   # STR Xt, [Xn, Xm] — reads the index
    (0xFFE00C00, 0xF8400000, ("rn",)),        # LDUR
    (0xFFE00000, 0xAB000000, ("rn", "rm")),   # ANDS
    (0xFFE00000, 0xEA000000, ("rn", "rm")),   # SUBS
    (0xFFE00C00, 0xF8000000, ("rn",)),        # STUR
]

#: Register-WRITE set of the same classes, same order. Kept separate from
#: `_ARM64_READS` because a READ-MODIFY-WRITE class (`add Xd, Xn, #k` with
#: `Rd == Rn`) is in both, and conflating the two is what makes a liveness
#: answer wrong in the permissive direction.
_ARM64_WRITES = [
    (0xFFE00000, 0x2A00FA00, ("rd",)),
    (0xFFE00000, 0x8B000000, ("rd",)),
    (0xFFE00000, 0xCB000000, ("rd",)),
    (0xFFE07C00, 0x9B007C00, ("rd",)),
    (0xFFFFFC1F, 0xCB0003E0, ("rd",)),
    (0xFF800000, 0x11000000, ("rd",)),
    (0xFF800000, 0x91000000, ("rd",)),
    (0xFF800000, 0x51000000, ("rd",)),
    (0xFF800000, 0xD1000000, ("rd",)),
    (0xFFE00000, 0xF9400000, ("rt",)),
    (0x9F000000, 0x90000000, ("rd",)),
    (0xFFC00000, 0xA9800000, ("rt", "rt2")),
    (0xFFC00000, 0xA8C00000, ("rt", "rt2")),
    (0xFFE00000, 0x52800000, ("rd",)),
    (0xFFE00000, 0xD2800000, ("rd",)),
    (0xFFE00000, 0xAA000000, ("rd",)),
    (0xFF800000, 0xF2800000, ("rd",)),
    (0xFF800000, 0x72800000, ("rd",)),
    (0xFFE00000, 0x12800000, ("rd",)),
    (0xFFE00000, 0x92800000, ("rd",)),
    (0xFFFF0FE0, 0x9A9F07E0, ("rd",)),
    (0xFFE00000, 0xF9000000, ()),
    (0xFFC00000, 0xA9400000, ("rt", "rt2")),
    (0xFFE0FC00, 0xAA200000, ("rd",)),
    (0xFFE0001F, 0xD4000001, ()),
    (0xFFE0FC00, 0x13001C00, ("rd",)),
    (0xFFE0FC00, 0x13003C00, ("rd",)),
    (0xFFE0FC00, 0x93407C00, ("rd",)),
    (0xFFC0FC00, 0x92401C00, ("rd",)),
    (0xFFC0FC00, 0x92403C00, ("rd",)),
    (0xFFC0FC00, 0x92407C00, ("rd",)),
    (0xFFE0FC00, 0x9AC00800, ("rd",)),
    (0xFFC0FC00, 0x9AC00C00, ("rd",)),
    (0xFFC0FC00, 0x9AC02000, ("rd",)),
    (0xFFC0FC00, 0x9AC02400, ("rd",)),
    (0xFFC0FC00, 0x9AC02800, ("rd",)),
    (0xFFE08000, 0x9B008000, ("rd",)),
    (0xFFC0FC00, 0xD340FC00, ("rd",)),
    (0xFFC0FC00, 0x9340FC00, ("rd",)),
    (0xFFC00000, 0xD3400000, ("rd",)),
    (0xFFD00000, 0x39400000, ("rt",)),
    (0xFFD00000, 0x39000000, ()),
    (0xFFD00000, 0x79400000, ("rt",)),
    (0xFFD00000, 0x79000000, ()),
    (0xFFD00000, 0x39800000, ("rt",)),
    (0xFFD00000, 0x79800000, ("rt",)),
    (0xFFD00000, 0xB9800000, ("rt",)),
    (0xFFD00000, 0xB9400000, ("rt",)),
    (0xFFE0FC00, 0xF8606800, ("rt",)),
    (0xFFE0FC00, 0xF8206800, ()),
    (0xFFE00C00, 0xF8400000, ("rt",)),
    (0xFFE00000, 0xAB000000, ("rd",)),
    (0xFFE00000, 0xEA000000, ("rd",)),
    (0xFFE00C00, 0xF8000000, ()),
    # Control flow writes NO register: a branch only moves the pc, and `ret`
    # reads X30. Listed explicitly because a word no row covers is taken to
    # write EVERYTHING, which would make every register live across every
    # `ret` and silence the pass on every program with a loop.
    (0xFFFFFC1F, 0xD65F0000, ()),
    (0xFFFFFC1F, 0xD61F0000, ()),
    (0xFC000000, 0x14000000, ()),
    (0xFC000000, 0x94000000, ("rt",)),       # BL — writes the link register
    (0xFF000000, 0x54000000, ()),
    (0x7F000000, 0x34000000, ()),
    (0x7F000000, 0x35000000, ()),
    (0x7F000000, 0x36000000, ()),
    (0x7F000000, 0x37000000, ()),
]


def _fields(word, table):
    """The register numbers `table`'s first matching row names, or `None` for
    a word no row covers — which every caller reads as "assume everything"."""
    for mask, value, fields in table:
        if (word & mask) != value:
            continue
        out = set()
        for f in fields:
            if f == "rd":
                out.add(word & 0x1F)
            elif f == "rn":
                out.add((word >> 5) & 0x1F)
            elif f == "rm":
                out.add((word >> 16) & 0x1F)
            elif f == "rt":
                out.add(word & 0x1F)
            elif f == "rt2":
                out.add((word >> 10) & 0x1F)
        out.discard(31)
        return frozenset(out)
    return None


#: A CALL reads its argument registers, and this compiler passes arguments in
#: x0…x7. A liveness check that ignored that would delete a value the callee
#: reads, so `reads_arm64` answers with all eight rather than with the caller's
#: own operand field.
_ARM64_CALL = ((0xFC000000, 0x94000000), (0xFFFFFC1F, 0xD63F0000))


def writes_arm64(word: int) -> frozenset:
    """Registers this instruction WRITES, or every register if unknown."""
    got = _fields(word, _ARM64_WRITES)
    return _ALL_REGS if got is None else got


#: Register 31 is the ZERO register for a register operand (SP only where the
#: encoding says so), so a read of 31 is a read of nothing.
_ALL_REGS = frozenset(range(31))

#: Rewrites attempted, for the no-fixed-point diagnostic.
_iters = [0]


def reads_arm64(word: int) -> frozenset:
    """Registers this instruction READS of a PRIOR value, or every register
    if unknown.

    The table is `arm64_step`'s decode read as data, and an instruction it does
    not cover returns `_ALL_REGS` rather than the empty set. That is the
    conservative answer and it is the only one a rewriter can use: "reads
    nothing" for an instruction we failed to decode would license deleting a
    value the program uses.
    """
    for mask, value in _ARM64_CALL:
        if (word & mask) == value:
            return frozenset(range(8))
    got = _fields(word, _ARM64_READS)
    return _ALL_REGS if got is None else got


# ── rules ───────────────────────────────────────────────────────────────────
@dataclass
class Rule:
    """One rewrite: what it matches, what it emits, and what proves it.

    `theorem` is the declaration in `lib/Peephole.lean` that says the rewrite
    leaves the machine model's registers, flags and memory as it found them.
    `side_conditions` are the hypotheses that theorem is stated with, in the
    order the proof states them; a rule whose matcher cannot discharge all of
    them does not fire. `apply` returns the replacement bytes for the window's
    FIRST instruction and how many instructions of the window survive, or
    `None` to decline.
    """
    name: str
    arch: str
    theorem: str
    side_conditions: tuple
    apply: object
    doc: str = ""

    def __call__(self, window, ctx):
        return self.apply(window, ctx)


#: The branch forms this backend emits, with the bit layout each one's
#: displacement has: `(class mask, class value, field mask AFTER the shift,
#: the field's lowest bit, the mask of everything that is NOT the field)`.
#:
#: A branch is the only reason a LATER instruction can read a value an EARLIER
#: one wrote, so this is what the liveness fixpoint needs — and it is also what
#: `_repatch_branches` writes back through after a rewrite, which is why the
#: PRESERVE mask is here rather than written out twice.
#:
#: **The field's lowest bit is 0 for `B` and 5 for every other row, and the
#: displacement is the field's value in INSTRUCTION counts** — the architecture
#: scales it by four, so a word carries it already divided. That was the bug
#: this table had: every row said `2`, which reads two bits too low for
#: `B.cond`/`CBZ`/`TBZ` and then divides the whole displacement by two on top,
#: so `arm64_branch_target` returned a WRONG index for every branch form this
#: backend emits. `_back_edges` (which no longer exists — the CFG replaced it)
#: then filtered every one of them out of range, the loop structure was invisible
#: to the liveness analysis, and the pass was left with a linear scan that cannot
#: see a loop.
#:
#: `keep` masks are `formal/arm64.py::Assembler.resolve`'s own preserve masks
#: for these classes (`0xff000000` for `B`, `0xff00000f` for `B.cond` because
#: the CONDITION lives in bits 0..3, `0xff00001f` for `CBZ`/`CBNZ` because Rt
#: does, `0xfff8001f` for `TBZ`/`TBNZ` because the BIT NUMBER is in 19..23).
_ARM64_BRANCHES = [
    (0xFC000000, 0x14000000, 0x03FFFFFF, 0, 0xFC000000),    # B
    (0xFF000000, 0x54000000, 0x007FFFF, 5, 0xFF00000F),     # B.cond
    (0x7F000000, 0x34000000, 0x007FFFF, 5, 0xFF00001F),     # CBZ  (W or X)
    (0x7F000000, 0x35000000, 0x007FFFF, 5, 0xFF00001F),     # CBNZ (W or X)
    (0x7F000000, 0x36000000, 0x003FFF, 5, 0xFFF8001F),      # TBZ  (W or X)
    (0x7F000000, 0x37000000, 0x003FFF, 5, 0xFFF8001F),      # TBNZ (W or X)
]


def _branch_slot(word: int):
    """The `_ARM64_BRANCHES` row `word` is, or `None`.

    `(field mask, the field's lowest bit, the mask of everything else)`, so
    that `arm64_branch_target` and `_repatch_branches` read the displacement
    out of the same two places and cannot disagree about where it is.
    """
    for mask, value, field, lsb, keep in _ARM64_BRANCHES:
        if (word & mask) == value:
            return field, lsb, keep
    return None


def _sign_extend(raw: int, width: int) -> int:
    """`raw` read as a two's-complement signed `width`-bit field."""
    return raw - (1 << width) if raw >> (width - 1) else raw


def arm64_branch_target(word: int, index: int):
    """The instruction index this word branches to, or `None`.

    **`None` for `BL`, `RET`, `BR Xn` and everything that is not a branch.** A
    `BL` is excluded on purpose: the callee is another function's region and
    this pass does not walk into it, so a call contributes its fall-through and
    its own eight argument-register reads and nothing else (`arm64_control`'s
    docstring is the argument for that).

    The answer is an INDEX into the entry list, so it is only meaningful with
    branch displacements expressed in instruction counts — which is what
    `Assembler.resolve` writes and what `_repatch_branches` keeps true after a
    rewrite moves the target.
    """
    slot = _branch_slot(word)
    if slot is None:
        return None
    field, lsb, _keep = slot
    disp = _sign_extend((word >> lsb) & field, field.bit_length())
    return index + disp


def _repatch_branch(word: int, disp: int) -> int:
    """`word` with its PC-relative displacement replaced by `disp`.

    The inverse of `arm64_branch_target` over the same table row, and it
    preserves every other field — the CONDITION of a `B.cond`, the REGISTER of
    a `CBZ`, the BIT NUMBER of a `TBZ` — through `keep`, because a branch that
    jumps to the right place and tests the wrong thing is a wrong answer with a
    correct-looking displacement.
    """
    slot = _branch_slot(word)
    if slot is None:
        raise CodegenError(
            f"the peephole pass asked to re-displace {word:#010x}, which is "
            "not a PC-relative branch")
    field, lsb, keep = slot
    width = field.bit_length()
    if not -(1 << (width - 1)) <= disp < (1 << (width - 1)):
        raise CodegenError(
            f"a branch displacement of {disp} instructions does not fit this "
            f"instruction's {width}-bit field ({word:#010x}); the image grew "
            "past what its branches can address")
    return (word & keep) | ((disp & field) << lsb)


def arm64_control(word: int) -> str:
    """`"branch"`, `"cond"`, `"call"`, `"return"` or `"other"`.

    * **branch** — an unconditional PC-relative `B`: the target and nothing
      else. There is no fall-through, and treating one as if there were would
      keep every register live down a path the program never takes.
    * **cond** — a `B.cond`, `CBZ`, `CBNZ`, `TBZ` or `TBNZ`: the target AND the
      fall-through.
    * **call** — `BL`: the call itself, then the fall-through. The callee is a
      different function's region and is NOT followed into; the registers it
      destroys are its own business here, because the only thing this pass asks
      about a register is WHO READS IT, and a `BL`'s own read set is its eight
      argument registers (`reads_arm64`'s `_ARM64_CALL` row). A caller-saved
      register the callee clobbers and the program never reads again is dead in
      the same sense here as it is in the theorem.
    * **return** — `RET`: nothing.
    * **other** — the fall-through, which is the safe answer for a class this
      function does not recognise.

    **An instruction that SETS THE FLAGS is deliberately not refined into a
    branch**, even though `CMP`/`SUBS`/`ADDS`/`ANDS` followed by a `B.cond` is
    the shape of every loop this backend emits. Naming those classes would buy
    precision — a window on the fall-through path would stop seeing the reads
    behind the branch — and it would cost a SECOND decode of the ALU classes,
    keyed on the S bit, whose failure mode is to delete an edge that exists.
    Over-approximating an edge costs a rewrite; under-approximating one costs an
    answer, and only one of those two is this pass's problem.
    """
    slot = _branch_slot(word)
    if slot is not None:
        return "branch" if (word & 0xFC000000) == 0x14000000 else "cond"
    if (word & 0xFC000000) == 0x94000000:
        return "call"
    if (word & 0xFFFFFC1F) == 0xD65F0000:
        return "return"
    return "other"


def _word_of(entry) -> int:
    """An entry's 32-bit word.

    Only the fixed-width backend has a CFG, a branch decoder or a rewriter that
    re-encodes an instruction, and every caller of this is one of them. Kept as
    one function so that the "is it 4 bytes" test lives in one place.
    """
    if len(entry.raw) != 4:
        raise CodegenError(
            "the peephole pass asked for a 32-bit word of a "
            f"{len(entry.raw)}-byte instruction; no x86-64 rule may do that")
    return struct.unpack_from("<I", entry.raw, 0)[0]


def arm64_successors(entries) -> list:
    """`[frozenset of instruction indices]` — the CFG of one image.

    **Index `len(entries)` is the EXIT node**, and every path ends there: a
    fall-through off the last instruction, a `RET` (which has no successor of
    its own), and a branch whose target is outside the image. Successors are
    computed from the branch words AS THEY STAND, which is why
    `_repatch_branches` re-derives every displacement after a rewrite — a
    target that has moved and a displacement that has not is a CFG with an
    edge into the middle of an instruction.

    A variable-length (x86-64) entry gets every later index, because building a
    CFG over variable-length instructions needs a decoder for every form and
    the only consumer is the arm64 rules; the over-approximating answer is the
    safe one and it is what the linear analysis this replaced gave.
    """
    n = len(entries)
    out = []
    for i, e in enumerate(entries):
        if len(e.raw) != 4:
            out.append(frozenset(range(i + 1, n + 1)))
            continue
        word = struct.unpack_from("<I", e.raw, 0)[0]
        kind = arm64_control(word)
        if kind == "return":
            out.append(frozenset({n}))
            continue
        succ = {i + 1}                      # `n` for the last one: EXIT
        if kind in ("branch", "cond"):
            target = arm64_branch_target(word, i)
            succ.add(target if target is not None and 0 <= target < n else n)
        out.append(frozenset(succ))
    return out


# ── arm64 rules ──
def _a_mov_self(window, ctx):
    """`mov xa, xa` — a copy of a register into itself. Nothing to do.

    Peephole's arm64/mov_self, and the rule that carries the pass's most
    important side condition — which is NOT a register condition:

      **The instruction must not be the low half of a PC-relative address
      pair.** `formal/arm64.py`'s `emit_adrp_add` emits `ADRP Xd, #page` and
      then `ADD Xd, Xd, #off` as ONE resolved pair: `Assembler.resolve`
      back-patches the ADRP's page delta and the ADD's within-page offset
      together, out of a single relocation recorded at the ADRP. When the
      label is page-aligned the offset is `#0`, so the pair's second
      instruction is byte for byte what this rule matches — and removing it
      leaves the program holding a PAGE where it wanted an ADDRESS.

      Measured, arm64, `tools/formal_fuzz.py --seed peephole-diff -n 30`:
      with the condition absent, generated program 11 printed
      `d 29 1 1 / d 0 0 0 / d` where CPython printed
      `29 1 1 0 29 / 0 0 0 29 5 / -21 -21`, and the two firings were
      `add x0, x0, #0` immediately after an `ADRP`. The Lean theorem is
      happy either way, because the model agrees the ADD is a no-op; what it
      does not know is that the ADRP above it was PATCHED to a page. So the
      condition lives here, beside the patch, and not in the theorem.

    The other conditions are the register ones: `imm == 0` (see `ArmInsn`'s
    docstring) and the two field names being equal, which `decode_arm64` has
    already refused to produce for a word naming 31 on either side.
    """
    if len(window) < 1:
        return None
    a = window[0].dec
    if a is None or a.form != "add_imm":
        return None
    if a.rd != a.rn or a.imm != 0:
        return None
    if ctx.after_adrp_add(window[0]):
        return None
    return b"", 1


def _a_copy_chain(window, ctx):
    """`mov xa, xb` ; `mov xc, xa`  ->  `mov xc, xb`.

    Peephole's arm64/copy_chain, and the one rule here with a LIVENESS
    condition: the rewrite does not write `xa`, so it is only sound when nothing
    reads `xa` — `_Ctx.window_dead` is that check and
    `peephole_arm64_copy_chain`'s fifth clause is what it discharges.

    `xc` and `xa` need not be the same register — that is what makes it a chain
    — and the theorem says so, so there is no `xc == xa` shortcut here.
    """
    if len(window) < 2:
        return None
    ea, eb = window[0], window[1]
    a, b = ea.dec, eb.dec
    if a is None or b is None or a.form != "add_imm" or b.form != "add_imm":
        return None
    if a.imm != 0 or b.imm != 0:
        return None
    if b.rn != a.rd:
        return None
    if not ctx.window_dead(a.rd, ea, eb):
        return None
    # Rewrite the FIRST word's Rd field. The class is fixed, so masking Rd out
    # and OR-ing the new one in is an instruction, not a guess — and it is
    # exactly the two-field change `peephole_arm64_copy_chain`'s `hdst` and
    # `hsrc` hypotheses name.
    new = (ctx.word(ea) & 0xFFFFFFE0) | b.rd
    return struct.pack("<I", new), 1


def _a_add_imm_fuse(window, ctx):
    """`add xd, xn, #i` ; `add xd, xd, #j`  ->  `add xd, xn, #(i+j)`.

    Peephole's arm64/add_imm_fuse. Two conditions and no liveness: the second
    must READ what the first wrote (`Rn2 == Rd1`) and WRITE the same register
    (`Rd2 == Rd1`), which is what makes the rewrite exact — the pair's
    register effect and the fused instruction's are then identical with no
    register skipped. `i + j < 4096` is the encodability condition and is the
    theorem's `hij`.
    """
    if len(window) < 2:
        return None
    ea = window[0]
    a, b = ea.dec, window[1].dec
    if a is None or b is None or a.form != "add_imm" or b.form != "add_imm":
        return None
    if b.rn != a.rd or b.rd != a.rd:
        return None
    total = a.imm + b.imm
    if total >= 0x1000:
        return None                      # `hij`: the fused immediate must fit
    # Keep sf/op/S and the class; replace Rd, Rn and the whole 12-bit
    # immediate field. Masking only Rd (which is what the copy chain needs, and
    # what this did first) leaves the OLD immediate behind, so
    # `add x6, x9, #5 ; add x6, x6, #7` fused to `add x6, x9, #5 | #7`.
    new = ((ctx.word(ea) & 0xFFE00000) | a.rd | (a.rn << 5)
           | ((total & 0xFFF) << 10))
    return struct.pack("<I", new), 1


_COPY_CHAIN = Rule("arm64/copy_chain", "arm64", "peephole_arm64_copy_chain",
                   ("rd < 31", "rn < 31", "the intermediate register is never "
                    "read again"), _a_copy_chain,
                   "two copies in a row folded into the second")

ARM64_RULES = [
    Rule("arm64/mov_self", "arm64", "peephole_arm64_mov_self",
         ("rd < 31", "rn < 31"), _a_mov_self,
         "a copy of a register into itself"),
    Rule("arm64/add_imm_fuse", "arm64", "peephole_arm64_add_imm_fuse",
         ("rd < 31", "rn < 31", "Rn2 == Rd1", "Rd2 == Rd1", "i + j < 4096"),
         _a_add_imm_fuse,
         "two additions to one register, fused"),
    _COPY_CHAIN,
]

ARM64_RULES_BY_NAME = {r.name: r for r in ARM64_RULES}


# ── x86-64 rules ──
def _x_mem_pair(window, ctx):
    """Two identical stores to one memory operand; or a load of what the
    store before it just wrote."""
    if len(window) < 2:
        return None
    a, b = window[0], window[1]
    if a.form == "mov_rm64_r64" and b.form == "mov_rm64_r64":
        if (a.mem_base, a.mem_disp, a.rm) == (b.mem_base, b.mem_disp, b.rm):
            return b"", 1
    if a.form == "mov_rm64_imm32" and b.form == "mov_rm64_imm32":
        if (a.mem_base, a.mem_disp, a.imm) == (b.mem_base, b.mem_disp, b.imm):
            return b"", 1
    if a.form == "mov_r64_rm64" and b.form == "mov_r64_rm64":
        if (a.reg, a.mem_base, a.mem_disp) == (b.reg, b.mem_base, b.mem_disp):
            return b"", 1
    return None


def _x_store_load(window, ctx):
    """`mov [b+d], r` ; `mov r, [b+d]`  ->  the store alone."""
    if len(window) < 2:
        return None
    a, b = window[0], window[1]
    if a.form != "mov_rm64_r64" or b.form != "mov_r64_rm64":
        return None
    if (a.rm, a.mem_base, a.mem_disp) != (b.reg, b.mem_base, b.mem_disp):
        return None
    return b"", 1


def _x_mov_self(window, ctx):
    """`mov r, r` — a register copied into itself."""
    if len(window) < 1:
        return None
    a = window[0]
    if a.form == "mov_r64_rm64" and a.reg == a.rm and a.mem_base is None:
        return b"", 0
    return None


def _x_imm_zero(window, ctx):
    """`add r, $0` / `sub r, $0` — an immediate that changes nothing.

    This is the rule that needs the FLAG-LIVENESS condition and the only one
    here that does: `add r, imm32` writes CF/OF/ZF/SF/PF on x86-64, so
    dropping the instruction is only sound when nothing downstream reads a
    flag. `add_zero_no_flag_read` proves the rewrite for the registers and
    memory, and the pass discharges the flag condition here — see
    The x86-64 model DOES carry the flags (`X86State.zf/sf/cf/of_`), so the
    theorem for this rule has to state them the way
    `peephole_arm64_mov_self` states them; the flag condition is the side
    condition, and where that theorem is written down is §3 of
    `bugs/FORMAL_peephole_rules_without_proofs.md`.
    """
    if len(window) < 1:
        return None
    a = window[0]
    if a.form not in ("alu_ri32:add", "alu_ri32:sub") or a.imm != 0:
        return None
    if a.op & 0x04:                 # the direction bit: a memory operand
        return None
    if not ctx.flags_dead_after(a.index + 1):
        return None
    return b"", 0


#: No x86-64 rule is enabled yet, and that is a fact about the PROOFS rather
#: than about the decoder: `x86_step`'s arms for the forms these rules need
#: (`mov r/m, r`, `mov r, r/m`, `alu r/m, imm32`) sit below about thirty other
#: tests, and each rule's Lean theorem has to discharge every one of them before
#: it can say the form is the one it rewrites. `bugs/FORMAL_peephole_rules_without_proofs.md`
#: records the measurement and the exact lemma each one is waiting on, which is
#: why this is a comment on an empty table rather than a rule with a `sorry`
#: beside it.
X86_RULES: list = []

#: Rules whose theorem is proved but whose MATCHER is not yet sound, kept out
#: of `ARM64_RULES` and named here so the gap is visible and testable rather
#: than absent.
#:
#: **EMPTY, and that is a measurement rather than an absence.** `arm64/copy_chain`
#: was the only member: its theorem was proved and its liveness matcher was not
#: sound for a loop, so `formal/examples/sqsum.mojo` answered 109 for 129 with
#: it on and `sum_range.mojo` never terminated. Three defects stood between it
#: and firing, all of them in this module rather than in the rule: `arm64_branch_
#: target` returned a wrong index for every branch form (so the loop structure
#: was invisible), the liveness analysis was a linear scan rather than a dataflow
#: over a CFG (so a loop-carried read was never seen), and no rule that deletes
#: an instruction re-derived the branch displacements it invalidates. All three
#: are fixed here and the rule is enabled; `test_formal_peephole.py` pins each
#: of them, and the corpus differential in `TestTheCorpus` is the end-to-end
#: claim. A rule that cannot discharge its side conditions goes HERE, not into
#: the registry: a theorem that says the rewrite preserves the machine model is
#: not a licence to fire it on a window whose conditions the pass cannot check.
PENDING_RULES: list = []

RULES = ARM64_RULES + X86_RULES


# ── the licence check ───────────────────────────────────────────────────────
def declared_theorems() -> set:
    """Every `theorem`/`lemma` name `lib/Peephole.lean` declares."""
    try:
        with open(LEAN_PEEPHOLE) as f:
            src = f.read()
    except OSError:
        return set()
    import re
    return set(re.findall(r"^\s*(?:theorem|lemma)\s+([A-Za-z_][\w'.]*)", src,
                          re.M))


def unlicensed_rules(rules=None) -> list:
    """Rules whose theorem `lib/Peephole.lean` does not declare.

    Empty is the only acceptable answer, and both backends check it before
    running the pass: a rewrite this module cannot point a proof at is not a
    rewrite this module performs. That is the mechanical form of "a rule
    without a proof is not allowed in" — it does not depend on anybody
    remembering which rules were checked.
    """
    have = declared_theorems()
    return [r for r in (rules if rules is not None else RULES)
            if r.theorem.split(".")[-1] not in have]


# ── the rewrite loop ────────────────────────────────────────────────────────
@dataclass
class Entry:
    """One instruction in the sequence being rewritten.

    `raw` is its bytes as they stand NOW, so a rewrite that replaces an
    instruction (`copy_chain` re-encodes its first word) is a change to `raw`
    and not a second pass over the image. `dec` is the decoded form, or `None`
    for an instruction the backend's decoder did not recognise — which matches
    no rule and, for liveness, reads every register.
    """
    raw: bytes
    dec: object
    reads: frozenset
    writes: frozenset
    flag_read: bool
    index: int = 0
    #: Where this instruction WAS, as a byte offset into the section. Carried
    #: rather than recomputed, because once the pass deletes something the
    #: survivors are no longer contiguous and an accumulating cursor is one
    #: deletion behind for the rest of the image — which put every label after
    #: the first deletion at its ORIGINAL address and left `mov_self` builds
    #: branching into deleted bytes.
    orig: int = -1


def _x86_flag_reads(form: str) -> bool:
    """Does this x86-64 form read the flags?

    The condition is where the `imm_zero` rule's soundness lives, so the list
    is the honest one over the forms `formal/x86_64.py` can encode: the
    conditional branches and `setcc`, the two compare forms, and `test`. A
    `call` is deliberately NOT here — it does not read the caller's flags,
    because the callee sets its own before reading any — and neither is a
    store or a move.
    """
    return (form.startswith("jcc") or form.startswith("setcc")
            or form in ("alu_rr:test", "alu_ri32:cmp", "alu_ri8:cmp",
                        "alu_ri16:cmp", "alu_ri32:add", "alu_ri32:sub",
                        "alu_ri32:and", "alu_ri32:or", "alu_ri32:xor",
                        "alu_rr:add", "alu_rr:sub", "alu_rr:and", "alu_rr:or",
                        "alu_rr:xor", "alu_rr:cmp", "alu_rr:inc", "alu_rr:dec",
                        "shift_imm8:shl", "shift_imm8:shr", "shift_imm8:sar",
                        "group3:not", "group3:neg", "cmov", "loop",
                        "jcxz", "jecxz", "jrcxz", "seta", "setb", "setg",
                        "setl", "sete", "setne", "setle", "setge", "seto",
                        "setno"))


def _decode_region(asm, text, arch):
    """Every instruction in the CODE region, or `[]` if there is none.

    The code region ends where the first interned string literal begins — the
    `str_` label convention `formal/x86_64_proof_gen.py` and
    `formal/x86_64_endtoend_test.py` already read to find the same boundary.
    The emitters append interned literals to the same section, so a rewriter
    that swept to the end of the buffer would be rewriting string bytes, and
    one that stopped at the first undecodable byte would stop at the first
    literal and find nothing.
    """
    base = asm._org
    end = len(text)
    for name, addr in asm.labels.items():
        if name.startswith("str_"):
            end = min(end, addr - base)
    if end <= 0:
        return [], len(text)
    entries = []
    if arch == "arm64":
        end -= end % 4
        for off in range(0, end, 4):
            word = struct.unpack_from("<I", text, off)[0]
            entries.append(Entry(raw=text[off:off + 4],
                                 dec=decode_arm64(word),
                                 reads=reads_arm64(word),
                                 writes=writes_arm64(word),
                                 flag_read=False, orig=off))
    else:
        from formal import x86_64_decode as DEC
        off = 0
        while off < end:
            try:
                insn = DEC.decode_one(text, off)
            except DEC.DecodeError:
                break
            if off + insn.length > end:
                break
            entries.append(Entry(raw=text[off:off + insn.length],
                                 dec=insn,
                                 reads=_x86_reads(insn),
                                 writes=_ALL_X86_REGS,
                                 flag_read=_x86_flag_reads(insn.form),
                                 orig=off))
            off = insn.next_offset
    for i, e in enumerate(entries):
        e.index = i
    return entries, end


_ALL_X86_REGS = frozenset(range(16))


def _x86_reads(insn) -> frozenset:
    """Registers an x86-64 instruction reads, or every register if unknown."""
    form = insn.form
    if form.startswith("jmp") or form.startswith("jcc") or form in (
            "call_rel32", "ret", "leave", "nop", "int3", "push_r64", "pop_r64"):
        return frozenset()
    if form.startswith("lea"):
        # LEA computes an address: it reads the base, not the memory.
        return frozenset({insn.rm} if insn.rm is not None else set()) \
            if insn.mem_base is not None else frozenset({insn.reg, insn.rm})
    if form.startswith("mov") or form.startswith("alu") or form.startswith(
            "shift") or form.startswith("movzx") or form.startswith("movsx"):
        out = set()
        if insn.reg:
            out.add(insn.reg)
        if insn.rm:
            out.add(insn.rm)
        return frozenset(out)
    # Anything else: assume every register is read.
    return frozenset(range(16))


class _Ctx:
    """What a rule's matcher may ask about the image it is rewriting."""

    def __init__(self, entries, arch):
        self.entries = entries
        self.arch = arch
        self._readers = None
        self._preds = None

    def moved(self) -> None:
        """The entry list changed shape, so every cached answer about it is void.

        `_run` calls this after each rewrite. Both of the derived tables here
        are keyed by instruction INDEX, so a single insertion or deletion
        invalidates every answer they can give.
        """
        self._readers = None
        self._preds = None

    def successors(self) -> list:
        """`[frozenset of instruction indices]` — this image's control-flow graph.

        The arm64 decoder's answer; for any other backend every instruction
        falls through to every later one, which is the linear over-approximation
        and therefore the safe direction.
        """
        if self.arch != "arm64":
            n = len(self.entries)
            return [frozenset(range(i + 1, n + 1)) for i in range(n)]
        return arm64_successors(self.entries)

    def predecessors(self) -> list:
        """`[frozenset]` — the transpose of `successors`, computed once per shape."""
        if self._preds is None:
            succ = self.successors()
            out = [set() for _ in succ]
            for i, edges in enumerate(succ):
                for s in edges:
                    if 0 <= s < len(out):
                        out[s].add(i)
            self._preds = [frozenset(p) for p in out]
        return self._preds

    #: The registers something reads at the END of the program, where no
    #: instruction does: x0 carries the entry function's return value (it
    #: becomes the process's exit status) and x30 the return address. Every
    #: `RET` reaches that point, so in `readers` these two carry an index of
    #: `len(entries)` and a rule asking whether a register is dead has to
    #: count them. **This is why a rule can never drop a write to x0 that a
    #: caller could read as the answer**, and it is why the old linear scan's
    #: `{0, 30}` seed existed — the seed was right and the scan that consumed it
    #: subtracted it away again.
    _EXIT_READS = frozenset({0, 30})

    def readers(self, reg: int) -> frozenset:
        """The indices of the instructions that READ `reg`, plus the EXIT index
        for a register the program's own result is made of.

        One table for the whole image rather than an answer per query, because
        the question `window_dead` asks is about the WHOLE image: a rewrite
        that stops writing a register has to know that nothing anywhere still
        reads it, and a per-query backward scan is the wrong shape for that.
        """
        if self._readers is None:
            out = {}
            exit = len(self.entries)
            for i, e in enumerate(self.entries):
                for r in e.reads:
                    out.setdefault(r, set()).add(i)
            for r in self._EXIT_READS:
                out.setdefault(r, set()).add(exit)
            self._readers = {r: frozenset(v) for r, v in out.items()}
        return self._readers.get(reg, frozenset())

    def window_dead(self, reg: int, first, second) -> bool:
        """May `first`'s write to `reg` be dropped, given `second` is deleted?

        The side condition `peephole_arm64_copy_chain`'s fifth clause asks for,
        and it is TWO conditions because the rewrite deletes one of the two
        instructions the theorem is about:

        * **`reg` is read nowhere in the image except at `second`.** The rewrite
          replaces `first` with a write to `second`'s destination and drops
          `second`, so `second`'s own read of `reg` is consumed by the rewrite
          itself and does not have to be dead — but every OTHER read is a place
          where the program sees a value the rewrite stopped producing. This is
          a whole-image condition, not a backward-liveness one, and the loop is
          the reason: in `cbz x4, . ; mov x5, x1 ; mov x1, x2 ; mov x3, x1 ;
          b .` the ONLY reader of x1 is `second`, yet a liveness that asks "is
          x1 read after `second`" says yes — the loop comes back round to
          `second` — and declines a rewrite that is sound.
        * **`second` is reachable only from `first`.** If any other edge lands
          on `second`, the rewrite runs `mov xc, xb` where the program had
          `mov xa, xb` above it, so `xc` gets `xb` instead of whatever was in
          `xa`. The converse cannot happen: `first` is never a branch and never
          falls past its own successor, so `first` always runs immediately
          before `second`.

        Both halves are decidable on the CFG `successors` builds, and both were
        wrong before: the analysis was a LINEAR scan, so a read inside a loop
        above the window was invisible, and nothing checked that a branch did
        not land in the middle of the window.
        """
        if not self.readers(reg) <= {second.index}:
            return False
        return self.predecessors()[second.index] <= {first.index}

    def after_adrp_add(self, entry) -> bool:
        """Is this instruction the `ADD` half of a resolved ADRP+ADD pair?

        `emit_adrp_add` records ONE relocation at the ADRP and
        `Assembler.resolve` writes two instructions from it, so the pair is
        only recognisable by position — which is why this needs the entry's
        index rather than the word alone.
        """
        i = entry.index
        if i == 0:
            return False
        prev = self.entries[i - 1]
        if len(prev.raw) != 4:
            return False
        word = struct.unpack_from("<I", prev.raw, 0)[0]
        return (word & 0x9F000000) == 0x90000000

    def word(self, entry) -> int:
        """The entry's 32-bit word, as it stands AFTER any rewrite so far.

        Read through `raw` rather than from the decoded form so that a rule
        which re-encodes an instruction and a rule which then matches the
        result see the same bytes. Only meaningful on the fixed-width backend;
        `x86_64` has no rules yet, and a rule that asked would get an error
        rather than a wrong word.
        """
        return _word_of(entry)

    def flags_dead_after(self, index: int) -> bool:
        """Is no flag read at or after instruction `index`?"""
        return not any(e.flag_read for e in self.entries[index:])


def peephole_arm64(asm, stats=None) -> int:
    """Run the arm64 rules over `asm`'s text, in place.

    Returns the number of INSTRUCTIONS removed, and fills `stats` (a
    `collections.Counter`) with one count per rule. Called from
    `ARM64Codegen.compile()` after `resolve()`, because the branch
    displacements it reads are the patched ones.
    """
    return _run(asm, "arm64", ARM64_RULES, stats)


def peephole_x86(asm, stats=None) -> int:
    """Run the x86-64 rules over `asm`'s text, in place.

    `X86_RULES` is empty, so this removes nothing today; it exists so the flag
    reaches this backend and the machinery — the decoder sweep, the fixed
    point, the `_Remap` — is exercised by the tests rather than waiting to be
    written twice.
    """
    return _run(asm, "x86_64", X86_RULES, stats)


def _run(asm, arch, rules, stats=None) -> int:
    """The rewrite loop, over both backends. Returns instructions removed.

    Fixed point: a pass that stops after one sweep misses `mov xa,xb ;
    mov xc,xa ; mov xd,xc`, where the first rewrite makes the second pair
    adjacent. `rounds` is a bound, not a hope — a loop that does not
    terminate is a compiler that does not return, and 64 is three orders of
    magnitude above what the shrinking window can need.
    """
    text = bytes(asm.sections["text"])
    if not text:
        return 0
    missing = unlicensed_rules(rules)
    if missing:
        raise CodegenError(
            "the peephole pass has rules with no proof in "
            f"{os.path.relpath(LEAN_PEEPHOLE, ROOT)}: "
            + ", ".join(f"{r.name} (theorem {r.theorem})" for r in missing)
            + ". A rule without a Lean theorem saying the rewrite preserves "
              "the machine model is not run; declare the theorem or drop "
              "the rule.")
    entries, code_end = _decode_region(asm, text, arch)
    if not entries:
        return 0
    ctx = _Ctx(entries, arch)
    counts = collections.Counter() if stats is None else stats
    removed = 0
    changed = True
    rounds = 0
    while changed and rounds < 64:
        changed = False
        rounds += 1
        i = 0
        while i < len(entries):
            _iters[0] += 1
            if _iters[0] > 200000:
                raise CodegenError(
                    f"peephole: no fixed point after {_iters[0]} window tests "
                    f"({len(entries)} instructions, round {rounds}); "
                    f"last at index {i}: "
                    + repr([getattr(e.dec, 'form', None) for e in entries]))
            window = entries[i:i + WINDOW]
            if not window:
                break
            hit = None
            for rule in rules:
                out = rule(window, ctx)
                if out is not None:
                    hit = (rule, out)
                    break
            if hit is None:
                if i + 1 >= len(entries):
                    break
                i += 1
                continue
            rule, (new_bytes, consumed) = hit
            counts[rule.name] += 1
            changed = True
            # A rule either REPLACES the window's first instruction (and drops
            # the rest) or DELETES the whole window. The two cases must not be
            # merged: deleting `entries[i+1:]` when the window is a single
            # instruction removes nothing, the loop makes no progress, and the
            # pass spins — which is exactly what it did before these two arms.
            if new_bytes:
                entries[i].raw = new_bytes
                entries[i].dec = _redecode(new_bytes, arch)
                entries[i].reads = reads_arm64(struct.unpack_from(
                    "<I", new_bytes, 0)[0])
                entries[i].writes = writes_arm64(struct.unpack_from(
                    "<I", new_bytes, 0)[0])
                del entries[i + consumed:i + len(window)]
                removed += len(window) - consumed
            else:
                del entries[i:i + consumed]
                removed += consumed
            for k, e in enumerate(entries):
                e.index = k
            ctx.moved()
            _repatch_branches(entries, _rebuild(text, entries, code_end)[1],
                              arch)
            if new_bytes:
                i += 1
        if not changed:
            break
    if not counts:
        return 0
    new_text, at = _rebuild(text, entries, code_end)
    _repatch_branches(entries, at, arch)
    _Remap(asm, at).apply()
    asm.sections["text"] = bytearray(new_text)
    return removed


def _repatch_branches(entries, at: list, arch: str) -> None:
    """Re-derive every branch displacement for the layout `at` describes.

    **Deleting bytes moves a branch's TARGET without moving the branch, and the
    displacement inside the branch is a number the assembler wrote once.** So a
    rule that removes an instruction between a branch and its target leaves the
    branch jumping four bytes too far — silently, in an image that still runs.
    That is not a hazard the pass can be allowed to have while any rule
    deletes anything, and no rule here is read-only: `mov_self` deletes, and
    `copy_chain` replaces its first instruction and drops the second.

    `at[old_offset]` is where an old byte offset ended up, so a branch's new
    displacement is `(at[old_target] - at[old_branch]) // 4` — the same
    arithmetic `formal/arm64.py::Assembler.resolve` does, over the same field
    layout, which is why `_repatch_branch` is the inverse of
    `arm64_branch_target` rather than a fourth decode. A target that fell
    inside a deleted range lands where the deletion collapsed to, which is what
    `at` already answers for it.

    Called after EVERY mutation rather than once at the end, because
    `arm64_successors` reads the branch words to build the CFG the next rule
    asks about: a target that has moved and a displacement that has not is a
    control-flow graph with an edge into the middle of an instruction, which
    `window_dead`'s second condition would then believe. Nothing
    on x86-64 is touched — no rule is enabled there and a variable-length
    instruction's displacement is not the 32-bit field this writes.
    """
    if arch != "arm64":
        return
    for e in entries:
        if len(e.raw) != 4:
            continue
        word = struct.unpack_from("<I", e.raw, 0)[0]
        slot = _branch_slot(word)
        if slot is None:
            continue
        field, lsb, _keep = slot
        at_here = at[e.orig]
        # The word's displacement is the OLD offset of its target, because that
        # is the only target it can still name. `at` maps it forward.
        old_target = e.orig + _sign_extend((word >> lsb) & field,
                                           field.bit_length()) * 4
        new = _repatch_branch(word, (at[old_target] - at_here) // 4)
        if new != word:
            e.raw = struct.pack("<I", new)


def _redecode(raw: bytes, arch):
    if arch == "arm64" and len(raw) == 4:
        return decode_arm64(struct.unpack_from("<I", raw, 0)[0])
    return None


def _rebuild(text, entries, code_end):
    """The new text, and the old-offset -> new-offset table.

    `at[old]` is the new offset of the same byte. A byte inside an instruction
    the pass removed maps to where that instruction WOULD have been — which is
    where a label naming it has to land, and is the answer that keeps every
    branch target on an instruction boundary.

    The cursor is each entry's OWN old offset (`Entry.orig`), never an
    accumulator: once the pass deletes something the survivors are no longer
    contiguous, and an accumulating cursor is one deletion behind for the rest
    of the image — which left every label after the first deletion at its
    original address, so a `mov_self` build branched straight into the bytes it
    had deleted.
    """
    out = bytearray()
    at = [0] * (len(text) + 1)
    filled = 0
    for e in entries:
        size = len(e.raw)
        pos = e.orig if e.orig >= 0 else filled
        if size == 0:
            continue
        # The gap between the last surviving instruction and this one is a
        # DELETED range, and every old offset in it lands where the deletion
        # collapsed to.
        for i in range(filled, pos):
            if i < len(at):
                at[i] = len(out)
        for k in range(size + 1):
            if pos + k < len(at):
                at[pos + k] = len(out) + k
        out.extend(e.raw)
        filled = pos + size
    for i in range(filled, code_end):
        if i < len(at):
            at[i] = len(out)
    # Everything from `code_end` on — the string-data pool the emitters append
    # after the code — is copied through and shifts by the same amount as the
    # code did. It is copied through rather than dropped because `_rebuild`
    # rebuilds the SECTION, and the section is one buffer.
    data_start = len(out)
    out.extend(text[code_end:])
    for i in range(filled, len(at)):
        at[i] = data_start + (i - filled)
    return bytes(out), at


class _Remap:
    """Move every address the assembler recorded, after the text moved.

    The pass deletes bytes, so every label, relocation and external-call stub
    above the deletion is now wrong by some delta — and `resolve()` has
    already run, because the branch displacements are what the rules read, so
    nothing will patch them a second time. `_Remap` is the whole of the fix and
    it is one table, applied to the assembler's own three.

    `info["cond_branches"]` lives on the CODEGEN rather than the assembler, so
    the codegen remaps its own pc list with the same table
    (`Arm64Codegen._peephole`). No rule here deletes a branch, so in practice
    every recorded pc survives; the table still answers for one that did not,
    rather than the two disagreeing about what happens then.
    """

    def __init__(self, asm, at):
        self.asm = asm
        self.at = at

    def _addr(self, a):
        base = self.asm._org
        i = a - base
        if i < 0 or i >= len(self.at):
            return a
        return self.asm._org + self.at[i]

    def apply(self):
        asm = self.asm
        asm.labels = {n: self._addr(a) for n, a in asm.labels.items()}
        asm.relocs = [(k, n, self._addr(p)) for k, n, p in asm.relocs]
        asm.extern_refs = [(s, self._addr(p), sz, kind)
                           for s, p, sz, kind in asm.extern_refs]
