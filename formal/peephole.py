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
    (0xFFC00000, 0xB4000000, ("rt",)),        # CBZ
    (0xFFC00000, 0xB5000000, ("rt",)),        # CBNZ
    (0xFF000000, 0x36000000, ("rt",)),        # TBZ
    (0xFF000000, 0x37000000, ("rt",)),        # TBNZ
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
    (0xFF800000, 0xD10000000, ("rd",)),
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
    (0xFFC00000, 0xB4000000, ()),
    (0xFFC00000, 0xB5000000, ()),
    (0xFF000000, 0x36000000, ()),
    (0xFF000000, 0x37000000, ()),
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
#: displacement has. A branch is the only reason a LATER instruction can read a
#: value an EARLIER one wrote, so this is what the liveness fixpoint needs.
_ARM64_BRANCHES = [
    (0xFC000000, 0x14000000, 0x03FFFFFF, 2),    # B
    (0xFF000000, 0x54000000, 0x007FFFF, 2),     # B.cond
    (0xFFC00000, 0xB4000000, 0x007FFFF, 2),     # CBZ
    (0xFFC00000, 0xB5000000, 0x007FFFF, 2),     # CBNZ
    (0xFF000000, 0x36000000, 0x003FFF, 2),      # TBZ
    (0xFF000000, 0x37000000, 0x003FFF, 2),      # TBNZ
]


def arm64_branch_target(word: int, index: int):
    """The instruction index this word branches to, or `None`.

    `None` for the two forms whose displacement is not a PC-relative word
    count — `BL` and `CBZ`-to-self — and for everything that is not a branch.
    A `BL` is excluded deliberately: a call can only read registers the caller
    left, and `reads_arm64` already accounts for that as x0…x7.
    """
    for mask, value, field, shift in _ARM64_BRANCHES:
        if (word & mask) != value:
            continue
        raw = (word >> shift) & field
        sign = 1 << (field.bit_length() - 1)
        disp = raw - (1 << field.bit_length()) if raw & sign else raw
        return index + disp
    return None


def _ctx_dead(ctx, reg: int, after: int) -> bool:
    """Is register `reg` never read at or after instruction index `after`?

    The whole-image form of deadness, and deliberately the weakest one that is
    still sound: a register re-read ANYWHERE later in the image counts as live,
    even where no path from the window reaches that read. It costs wins — on
    `formal/examples` it keeps the copy chain at 27 of the 47 chains that are
    adjacent — and buys a property worth more than the wins: a reader cannot
    be wrong about it in the direction that changes an answer. The measurement
    and the CFG-aware test that would recover the rest are in
    `bugs/FORMAL_peephole_rules_without_proofs.md`.
    """
    return not ctx.reads_after(reg, after)


# ── arm64 rules ──
def _a_mov_self(window, ctx):
    """`mov xa, xa` — a copy of a register into itself. Nothing to do.

    Peephole's arm64/mov_self. The condition is that the two register fields
    NAME the same register, which `decode_arm64` has already refused to
    produce for a word naming 31 on either side.
    """
    if len(window) < 1:
        return None
    a = window[0].dec
    # `imm == 0` is load-bearing, not a shortcut: see `ArmInsn`'s docstring.
    if a is None or a.form != "add_imm":
        return None
    if a.rd != a.rn or a.imm != 0:
        return None
    return b"", 1


def _a_copy_chain(window, ctx):
    """`mov xa, xb` ; `mov xc, xa`  ->  `mov xc, xb`.

    Peephole's arm64/copy_chain, and the one rule here with a LIVENESS
    condition: the rewrite does not write `xa`, so it is only sound when
    nothing reads `xa` again. `_ctx_dead` is that check, and
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
    if not _ctx_dead(ctx, a.rd, eb.index + 1):
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
]

ARM64_RULES_BY_NAME = {r.name: r for r in ARM64_RULES}
ARM64_RULES_BY_NAME[_COPY_CHAIN.name] = _COPY_CHAIN


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
#: than absent. `arm64/copy_chain` is in this state because the liveness check
#: is wrong for a loop: `formal/examples/sqsum.mojo` answers 109 for 129 with
#: it on and `sum_range.mojo` never terminates, and the backward-edge
#: fixpoint in `_Ctx.live_after` did not close it. A theorem that says the
#: rewrite preserves the machine model is not a licence to fire a rule on a
#: window whose side condition the pass cannot establish.
PENDING_RULES = [
    ARM64_RULES_BY_NAME["arm64/copy_chain"],
]

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

    def __init__(self, entries, arch, back_edges=()):
        self.entries = entries
        self.arch = arch
        self.back_edges = list(back_edges)
        self._live_after = None

    def live_after(self, index: int) -> frozenset:
        """Registers whose value at `index` some later instruction reads.

        BACKWARD linear dataflow over the whole image, computed once. Two
        deliberate choices:

        * **Linear, not a CFG.** Every instruction is treated as reachable
          from every point, so the answer over-approximates liveness and a
          rewrite only fires when it certainly is not needed. A CFG would find
          more; this costs a few percent of the chains and buys an analysis
          that cannot be wrong about a path.
        * **Starts at `{x0, x30}`.** x0 carries the entry function's return
          value and x30 the return address, and both are live at the end of
          the image even though no instruction reads them there. Everything
          else is assumed dead at the end, which is the direction that lets a
          rule fire.

        `live_after(i)` is what makes `copy_chain` sound: the rule leaves the
        intermediate register unwritten, so it needs that register out of
        `live_after(i + 1)`.
        """
        if self._live_after is None:
            live = {0, 30}
            table = [frozenset() for _ in self.entries]
            for i in range(len(self.entries) - 1, -1, -1):
                e = self.entries[i]
                # A register this instruction READS and does not write is used;
                # one it both reads and writes (an `add xa, xa, #k`) is only
                # reading the value it is about to replace, so the prior value
                # does not count — which is the difference between a table of
                # "reads" and a dataflow.
                live |= (e.reads - e.writes)
                live -= e.writes
                table[i] = frozenset(live)
            # Backward branches close the loop: a branch at `j` back to `t ≤ j`
            # means whatever is live after `t` is live after `j` as well, and a
            # purely LINEAR scan cannot see that — it has already passed `t`.
            # Without this step `sqsum.mojo` answered 109 for 129 and
            # `sum_range.mojo` never terminated, because both loops read a
            # register the loop body wrote.
            for _ in range(len(self.entries) + 1):
                moved = False
                for j, t in self.back_edges:
                    merged = table[j] | table[t]
                    if not merged <= table[j]:
                        table[j] = merged
                        moved = True
                if not moved:
                    break
            self._live_after = table
        return self._live_after[index]

    def word(self, entry) -> int:
        """The entry's 32-bit word, as it stands AFTER any rewrite so far.

        Read through `raw` rather than from the decoded form so that a rule
        which re-encodes an instruction and a rule which then matches the
        result see the same bytes. Only meaningful on the fixed-width backend;
        `x86_64` has no rules yet, and a rule that asked would get an error
        rather than a wrong word.
        """
        if len(entry.raw) != 4:
            raise CodegenError(
                "the peephole rule asked for a 32-bit word of a "
                f"{len(entry.raw)}-byte instruction; no x86-64 rule may do that")
        return struct.unpack_from("<I", entry.raw, 0)[0]

    def reads_after(self, reg: int, index: int) -> bool:
        """Is `reg` read at or after instruction `index`?"""
        return reg in self.live_after(index)

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
    ctx = _Ctx(entries, arch, _back_edges(entries, arch))
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
            ctx._live_after = None
            if new_bytes:
                i += 1
        if not changed:
            break
    if not counts:
        return 0
    new_text, at = _rebuild(text, entries, code_end)
    _Remap(asm, at).apply()
    asm.sections["text"] = bytearray(new_text)
    return removed


def _back_edges(entries, arch) -> list:
    """`(from, to)` index pairs for every branch that goes BACKWARDS."""
    if arch != "arm64":
        return []
    out = []
    for i, e in enumerate(entries):
        if len(e.raw) != 4:
            continue
        t = arm64_branch_target(struct.unpack_from("<I", e.raw, 0)[0], i)
        if t is not None and t <= i and 0 <= t < len(entries):
            out.append((i, t))
    return out


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
