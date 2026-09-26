

<!--
  This file is now the ARM64-SIDE LEDGER ONLY.

  It was an append-only scratch ledger that had grown to hold four different
  subsystems at once, which made "the bug docs" ambiguous. The x86-64 formal
  and codegen findings have been split out into proper per-bug documents in
  bugs/; the arm64 entries stay here because they are the active line of work.

  Moved out, and where it went:

    nested comprehensions (arm64 root cause + x86-64 handoff + shape matrix)
        -> bugs/CODEGEN_nested_comprehension.md
    x86-64 `structs` keyword build failure; `len(x)` linking to a libc symbol
        -> bugs/FORMAL_x86_64_formal_backend_gaps.md
    x86-64 end-to-end proof work: step lemmas, the vacuous setcc lemma, the
    memory-separation statements, admitted sorries
        -> bugs/FORMAL_x86_64_end_to_end_proof.md
    `check-native-dumpfull` writing no fire.ci: the ~192 GB runaway, the 55 GB
    ceiling, and the attribution ruling-out
        -> bugs/CODEGEN_bootstrap_resource_blowup.md
    `make bootstrap` verify failing on ~14 files
        -> already tracked in
           bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md

  New entries: prefer a bugs/<TOPIC>.md document per bug. Append here only for
  arm64 codegen/proof work in flight, since that is what this file is now for.
-->

---

## BUG: `ARM64Codegen.__init__()` does not accept `dylib_syms` — every formal build fails

**Status:** FIXED (reported 2026-09-25, `test_x86_64_examples.py` back to 43/43
within the minute; the arm64 side now takes the same `dylib_syms` keyword the
x86-64 side does). Kept for the record. **Affects:** every `./fire.py build
--formal` (arm64 is the default backend), which died before emitting a byte.
**Found:** 2026-09-25, from `test_x86_64_examples.py`, whose arm64 reference leg
went from 43/43 to 0/43 with:

```
TypeError: ARM64Codegen.__init__() got an unexpected keyword argument 'dylib_syms'
```

**Not mine to fix** — the in-flight dylib-linking change in `formal/build.py`
introduces it. I have completed the x86-64 half of the same interface
(`X86_64Codegen.__init__(test_input, extern_style, dylib_syms)`, mangling the
callee to the linked dylib's exported spelling), so only the arm64 side is
outstanding.

### The mismatch

`formal/build.py:540-551`

```python
def _make_codegen(arch: str, fmt: str, test_input: int, dylib_syms: dict = None):
    if arch == "arm64":
        return ARM64Codegen(test_input=test_input, dylib_syms=dylib_syms)
```

`formal/arm64_codegen.py:374`

```python
def __init__(self, test_input: int = 10):
```

### Fix

Either accept and store the map in `ARM64Codegen.__init__` (and use it at the
call site the way `formal/x86_64_codegen.py:_emit_call` does), or drop the
keyword at `formal/build.py:551` until the arm64 side is ready. The first is
what keeps `--backend=arm64` and `--backend=x86_64` on one interface.

### Why it is worth catching with a test rather than by eye

`_make_codegen` is shared by both backends now, so a keyword added for one of
them breaks the other at *runtime*, and only on the branch that takes it —
nothing at import time, and a build-only check that never reaches the
constructor's mismatch would still be green. `test_x86_64_examples.py` catches
it because it builds the same example through BOTH backends.

## arm64 instruction coverage: audited, and the highest-value gaps closed

Not a bug — a survey, kept here because the answer is not guessable and the
tooling to re-derive it should not have to be written twice.

`tools/arm64_insn_audit.py` answers "what can the codegen not emit, weighted
by how often a compiler actually emits it". Counting the encoder table is not
the same question: this backend had 52 encoders and still could not express a
single conditional branch on a comparison's flags.

Method: take the encoder inventory from `formal/arm64.py`, take the real
instruction mix by disassembling 200 system binaries (4.0M instructions, 420
distinct mnemonics), and rank the difference. Pointer-authentication
instructions (`pacibsp` and friends, ~92k) are excluded **by decision, and the
exclusion is printed** — a backend with nothing to authenticate has no use for
them, and hiding that in a filter would be dishonest accounting.

| | before | after |
|---|---|---|
| encoders | 52 | 69 |
| covered | 86.2% | **92.0%** |
| genuinely uncovered | 11.5% | **5.7%** |

Added, in the order the audit said they mattered:

* **B.cond**, all 14 conditions — by far the biggest single gap (~154k
  occurrences). `if a < b` was `cmp` + `cset` + `cbz` + branch: three
  instructions, one materialising a boolean that the branch immediately reads
  back.
* **CSEL / CSINC / CSINV / CSNEG** (~40k) — a conditional *expression* should
  not become a branch. With Rn = Rm = XZR, CSEL is exactly CSET, which is how
  the existing `encode_cset_*` is now expressed.
* **TBZ / TBNZ** (~75k) — `if x & (1 << n):` was a mask, a compare and a
  branch. Bits 0-31 only: the architectural b40 form relocates imm14, and
  encoding that from memory of the spec is how you get a branch to the wrong
  address, so bits >= 32 raise instead.
* **LDUR / STUR** (~45k) — unscaled access, which in practice means the
  NEGATIVE displacement a scaled-offset load cannot express.
* **LDRH / STRH / LDRSH / LDRSW / LDRSB** (~39k) — the remaining access widths.
* **TST / CMN / SUBS** (~36k) — flag-setting ALU with no or minimal result.

### `test_arm64_encoders.py`: every encoder against `as -arch arm64`

209 instructions, each assembled by Apple's assembler and compared **byte for
byte**. This is a real oracle rather than a hand-derived bit layout, and it
immediately earned its keep — six of the new encoders were wrong on first
write and the harness said exactly how:

    csel family   CSNEG and CSINV have bit 31 SET (0xDA..), not clear
    ldrh / strh   the immediate scales by /2, not /4
    tst           no destination, so the Rn field is 31
    cmn           64-bit base has bit 30 clear (0xAB..)
    b.cond        imm19 counts INSTRUCTIONS, so the range is +-1MB — my first
                  version allowed 2MB, which lands a branch 1MB from where the
                  reloc intended and passes every value-level test

That last one is why the test also asserts the bound is **enforced** rather
than clamped: a silently truncated branch offset produces a program that runs
and computes something else.

One trap worth writing down: `otool -s __TEXT __text` prints each word in
display order, so decoding it little-endian yields the byteswapped
instruction and every comparison then fails for the same uninteresting reason.

### Not yet wired up: using B.cond and CSEL in the codegen

The encoders exist and are verified; the codegen does not emit them yet. It
still materialises a boolean and branches, via the `_record_cond_branch()` +
`encode_cbz_xn` pattern (66 `cset` sites). Wiring B.cond means giving the
comparison-emitting path a way to say "branch on these flags" instead of
"produce 0/1 and branch on it", which is a behaviour change on the hot path
for every `if` — worth doing, worth doing with the full gate behind it, and
not worth folding into a commit that also adds seventeen encoders.

Also still uncovered and genuinely worth having, in the audit's order:
`ccmp` (0.34%), `rev`, `ror`, `ubfx`/`ubfiz`, `madd`, and the float/convert
family (`fmov`, `ucvtf`, `fcmp`) — none of which this one-word integer model
has a use for yet.


## Emitting the new instructions: what it actually bought (measured, not assumed)

Wired up where it does NOT touch the proof-visible structure, since the
proof-generator work is deliberately deferred:

* **CSEL for a conditional expression** (`a if c else b`) and for
  short-circuit **`and`/`or`** as a value.
* **LDUR/STUR for spill slots** — a spill slot is a fixed displacement from
  the frame pointer, which is exactly what the unscaled form is for.

### The measurement, and the part that is not a win

A benchmark mixing a ternary, `and`, `or` and fourteen spilled locals, built at
818a851 and again after:

    total   176 -> 174 instructions
    sub     38 -> 33     ldr  3 -> 0     str  2 -> 0
    ldur    0 ->  3      stur 0 -> 2
    b        4 ->  1     cbz  3 -> 1     cbnz 1 -> 0
    csel    0 ->  3
    ldp     14 -> 18     stp 14 -> 18     <-- the cost

Same result (253) before and after, so nothing changed semantically.

**LDUR/STUR is the real win**: 10 instructions gone, because each spill access
was `mov` + `sub` + access and is now one instruction.

**CSEL is NOT an instruction-count win here, and the +8 stack pairs say why.**
The three CSELs replace three branches (-6 branch/cbz/cbnz) but need four
push/pop pairs to keep the operands live across the flag-setting compare,
because arm evaluation clobbers the flags. For a ternary whose arms are pure
and therefore *cheap* — which is exactly what the purity guard allows — two
`stp`/`ldp` pairs cost more than the branch they remove. It buys:

  * fewer BRANCHES, which is a pipeline argument, not a size one, and
  * fewer basic blocks, which is what `arm64_proof_gen` has to filter around:
    it picks a block ending in a recorded `cbz` as an entry condition, and a
    short-circuit CBZ ends a block identically — the reason
    `_cond_branches` exists as a filter at all. CSEL removes that ambiguity
    rather than adding to it.

So: keep both, but the honest summary is "10 instructions smaller and 6 fewer
branches", not "CSEL made it smaller".

The way to make CSEL a genuine size win is to stop needing the stack — keep
the two arms in registers that expression evaluation does not clobber. X9/X10
are not safe for that today (`_emit_list_base` alone uses X9), so it needs a
reserved-scratch convention first. Worth doing; not done here.

### Still blocked, and only on the deferred proof work

`B.cond` is the biggest single instruction in the audit (~154k occurrences) and
the codegen still does not emit it, because **all four** conditional sites
(`if`/`elif`, `while`/`for`, the ternary, and a comprehension's generator
conditions) call `_record_cond_branch()`, and `arm64_proof_gen` finds an entry
condition by looking for a block whose terminator is a recorded `cbz` and
reading the register that CBZ tests. A `B.cond` there is neither a `cbz` block
nor a register, so the proof would silently lose the condition. That is the
work being deferred, and it is the only thing standing between the current
tree and the largest win available in the audit.


## The largest codegen win in the project: immediates above 4095

Found by asking where the instructions actually GO, after the audit's
instruction-count measurement came out suspiciously small.

`_emit_sub_imm` / `_emit_add_imm` split any immediate above 4095 into a chain
of 4095-sized `SUB`/`ADD` instructions. The formal backend subtracts its 128KB
scratch from the frame pointer at the top of **every** list base, dict,
comprehension, container append and indexed access — and 131072 is
`32 << 12`, which arm64's `SUB (immediate)` encodes in ONE instruction via the
optional `LSL #12` on its 12-bit field.

So every container operation in the backend was paying **33 instructions** for
an address computation, and a program using lists and dicts was roughly 4x
larger than it needed to be:

    container benchmark, before -> after
      997 -> 261    (shifted immediates)
      261 -> 246    (fold the frame-base SUB)
      246 -> 225    (one SUB from X29 instead of mov + three subs)

Same answer (58) at every step. The 12 new cases in
`test_arm64_encoders.py` check the `sh` variants against `as -arch arm64`, so
the encoding is the assembler's and not a bit layout recalled from the spec.

The lesson worth keeping: an instruction-count audit that only asks "can we
express what a compiler expresses" misses this entirely. `sub` was fully
covered the whole time. The defect was not a missing instruction but a
*misuse* of one that was present — which is a different question, and the one
that actually decides how big the generated code is.

Also folded while in there: `_emit_list_base` emitted `mov x9, x29` followed
by up to three separate adjustments, when the whole displacement is a
compile-time constant and fits the shifted form in one.


## What is left in the instruction work, measured rather than guessed

Two items remain, and both are recorded here with their real cost so the next
person does not have to re-derive them.

**`B.cond` (the biggest single item in the audit, ~154k occurrences) is now
wired at every site that has flags to branch on**, and wiring it turned up two
real bugs rather than just closing a gap.

A comparison becomes `CMP` + `B.cond` — one branch, and no boolean round trip
through a register. It fires at `if`/`elif`, `while`, the `for`-range test, the
ternary's fallback, and a comprehension's generator conditions. It
deliberately does *not* fire for a call condition, a truthiness test, or a
short-circuit chain: those genuinely need a value, because there are no flags
to read. Branching on the FALSE case keeps the block shape byte-identical to
the old `cbz` lowering, so nothing downstream had to move.

Two bugs, both found by the first thing that actually ran the code:

  1. `Assembler.resolve()` had cases for `B`, `BL`, `CBZ` and `CBNZ` but none
     for `B.cond`. The displacement was never written, `imm19` stayed 0, and
     every conditional branch pointed at **itself**: `if a > b:` with a false
     condition was a one-instruction infinite loop. The first fix was wrong in
     a way worth recording — it identified the opcode with
     `insn & 0xff00001f == 0x54000000`, masking off the cond field and then
     comparing against a *zero* cond, which can never match. The top byte
     alone identifies `B.cond`; both the encoder and the model hit this same
     trap independently.

  2. `test_arm64_encoders.py` compares four instruction *bytes* against `as`.
     It therefore cannot see a missing *relocation*, which is why a perfectly
     green encoder suite coexisted with a compiler that hung on any false
     comparison. `test_arm64_emission.py` now checks that no branch resolves
     to its own address; that check was verified to fail when the fix is
     removed, so it is not vacuous.

The proof side is deliberately unfinished — the generator is to be thinned and
closed with `sorry` once the instruction work is done, and the `sorry`s
attacked after that.

**A reserved scratch-base register: measured, and the answer is no.** The
claim here used to be that it "needs measurement across a corpus, not one
benchmark". Measured:

| corpus | instructions | wide-offset path | share |
|---|---|---|---|
| 43 `formal/examples` | 1386 | 0 | 0.0% |
| 30 locals (21 spilled) | 83 | 0 | 0.0% |
| 45 locals (36 spilled) | 141 | 28 | 19.9% |
| 60 locals (51 spilled) | 201 | 58 | 28.9% |
| 80 locals (71 spilled) | 281 | 98 | 34.9% |

The wide-offset path — the only thing a base register would eliminate — is
`mov/add X17, X29` + `sub X17, X17, #off` before a load/store, and it is
reached only when `_spill_off` exceeds 256, i.e. once a function has roughly
**36 simultaneously-live spilled locals**. Up to that point the `ldur`/`stur`
fast path (signed imm9, -256 reachable) already covers every slot in one
instruction, and a base register buys exactly nothing: 0 of 1386 instructions
across the whole example corpus.

Against that, the cost is universal. The register has to come out of the ten
callee-saved registers, so a function gets 9 register locals instead of 10 and
one more value spills; `_npairs` goes 5 -> 6, adding an `stp` and an `ldp` to
*every* prologue and epilogue. So the trade is: +2 instructions everywhere,
plus a slightly higher chance of spilling, in exchange for 20-35% of a
function that keeps 36+ values live simultaneously.

Not worth doing. The regime that would benefit is rare enough that the
universal cost dominates, and the original objection on this page was right
for a better reason than the one it gave.

Two smaller things were checked and are already optimal:

  * `add x4, x9, #8` + `add x4, x4, x1, lsl #3` (17 occurrences) is an
    address computation that cannot be one instruction — arm64 has no
    scaled-index addressing, that is an x86-ism.
  * The `and`/`or` and ternary CSEL paths cost two push/pop pairs, which is
    the price of evaluating both arms without a stack frame convention for
    expression temporaries. Making them one needs registers that expression
    evaluation provably does not clobber; X9 alone is used by
    `_emit_list_base`.


## `for i in range(a, b)` never terminated: the loop had no exit test at all

Found while wiring `B.cond` into the for-range test. This is the worst-shaped
bug in this file, because it is not a wrong answer — it is a hang, and it was
sitting in a code path the test suite never entered.

The for-range lowering called `_emit_cmp(...)` at the top of the loop and then
**never branched on the CSET it left behind**. The emitted loop was:

```
loop:  cmp x0, x1          ; i vs end
       cset x0, lo         ; x0 = (i < end)   <- and then?
       add x0, x20, #0x0   ; x0 is overwritten here
       ...body...
       b loop
```

`cset` is flags-to-register; nothing consumed the register. There is no `cbz`
anywhere in the loop and no other exit, so control reaches the end of the
function's range only by running out of stack.

Every `for i in range(...)` therefore hung. It survived because comprehensions
use their own loop emitter, and the range cases in `test_formal_run.py` went
through comprehensions rather than a `for` statement.

Two bugs, both fixed:

  * **The missing exit test.** Now `CMP` + `B.cond` on the flags, the same
    shape as the `while` condition. Seven cases in `test_formal_run.py`
    (ascending, empty, descending, stride 2, single-argument, nested, `break`).

  * **Descending ranges exited immediately.** The test was hard-coded
    `i < end`, so `range(4, 0, -1)` — whose *counter* already advanced
    correctly, via `SUB` — compared `4 < 0` and did nothing. The comparison now
    follows the step's direction. A step whose sign is only known at runtime
    (`range(a, b, -step)`) is now **refused with a clear error** rather than
    compiled to a loop bound that is the wrong way round: a wrong answer, not
    a slow one.

### FIXED: comparisons involving negative values were unsigned

Was: `range(-3, 2)` returned 0 and `if -3 < 2: return 1` returned 0. Two
independent causes, both in `formal/types.py`, and both had to be fixed — the
first alone does not make `range` work.

**1. `infer_expr` reported a negated literal as typeless.** The bare-literal
rule returns `None` so a literal takes its type from context, and `UnaryOp`
recurred into the operand — so `UnaryOp('-', IntLiteral(3))` was `None` too.
With both operands typeless, `common_type` was `None`, `cmp_signed(None)` is
`False` (`formal/types.py:260`), and the comparison was emitted with the
*unsigned* condition codes. `-3` is `0xFFFF...FD` as a `UInt64`, so `-3 < 2` is
false. A negative value cannot be an unsigned one, so `infer_expr` now reports
`IntType(64, True)` for `UnaryOp('-', IntLiteral(v))` with `v != 0`. Narrow on
purpose: `0 - 3` is a `BinaryOp` and stays typeless, and negating a *variable*
still recurses, so only a literal negative changes behaviour.

**2. A range's counter was seeded with the unsigned default.** Even with (1),
`range(-3, 2)` still did not run:

```python
rt = DEFAULT_INT_TYPE          # IntType(64, signed=False) -- UNSIGNED
for a in rargs:
    rt = common_type(rt, infer_expr(a, ...))
```

`common_type` resolves mixed signed/unsigned to *unsigned*, so seeding with the
unsigned default made the counter unsigned for **every** range, whatever the
bounds said. Seeding with `None`, which `common_type` treats as neutral, fixes
it and leaves every all-positive range resolving to the default exactly as
before.

Both the `CSET` value path and the `B.cond` branch path read this one function,
so they cannot now disagree about signedness — which was the whole reason this
was left alone while the `B.cond` work was in flight.

Verified: arm64 formal 40/3/0 and x86-64 43/0/0 both unchanged (this is a shared
file), runtime 33/33, emission 5/5, imports 11/11, dylib 9/9. Four cases added,
including a positive comparison to guard the other direction and a counted
`range(-3, 2)` — counted rather than summed, because the sum is `-5` and every
expected value in this suite has to fit in a byte.

## `for i in range(a, b)` never terminated: the loop had no exit test at all

Found while wiring `B.cond` into the for-range test. This is the worst-shaped
bug in this file, because it is not a wrong answer — it is a hang, and it was
sitting in a code path the test suite never entered.

The for-range lowering called `_emit_cmp(...)` at the top of the loop and then
**never branched on the CSET it left behind**. The emitted loop was:

```
loop:  cmp x0, x1          ; i vs end
       cset x0, lo         ; x0 = (i < end)   <- and then?
       add x0, x20, #0x0   ; x0 is overwritten here
       ...body...
       b loop
```

`cset` is flags-to-register; nothing consumed the register. There is no `cbz`
anywhere in the loop and no other exit, so control reaches the end of the
function's range only by running out of stack.

Every `for i in range(...)` therefore hung. It survived because comprehensions
use their own loop emitter, and the range cases in `test_formal_run.py` went
through comprehensions rather than a `for` statement.

Two bugs, both fixed:

  * **The missing exit test.** Now `CMP` + `B.cond` on the flags, the same
    shape as the `while` condition. Seven cases in `test_formal_run.py`
    (ascending, empty, descending, stride 2, single-argument, nested, `break`).

  * **Descending ranges exited immediately.** The test was hard-coded
    `i < end`, so `range(4, 0, -1)` — whose *counter* already advanced
    correctly, via `SUB` — compared `4 < 0` and did nothing. The comparison now
    follows the step's direction. A step whose sign is only known at runtime
    (`range(a, b, -step)`) is now **refused with a clear error** rather than
    compiled to a loop bound that is the wrong way round: a wrong answer, not
    a slow one.

### Still open: comparisons involving negative values are unsigned

Found in the same pass, and NOT fixed, because the root cause is a type bug
that would invalidate the whole condition-code table.

`range(-3, 2)` returns 0. So does `if -3 < 2: return 1`. Arithmetic is fine
(`0 - 3 + 5` is 2); only *comparisons* are wrong, and only when a negative
value is involved:

`infer_expr` returns `None` for `UnaryOp('-', IntLiteral(3))` — the parser
keeps `-3` as a negation, not a negative literal, and nothing gives it a type.
`common_type` then returns `None`, and `cmp_signed(None)` is `False`
(`formal/types.py:260`), so the comparison is emitted with the **unsigned**
condition codes. `-3` is `0xFFFF...FD` as a `UInt64`, so `-3 < 2` is false.

This is backend-wide, not a loop bug, which is why it is recorded here rather
than papered over in the for-range path. The fix is in `formal/types.py`:
give a negated literal a signed type. It has to be done there, because the
`B.cond` lowering deliberately shares `_cmp_conds` and the
`cmp_signed(common_type(...))` decision with the `CSET` value path — so
fixing it in one place fixes both, and fixing it in only one place would make
a comparison branch one way and evaluate the other. `formal/model.py`'s flag
lemmas (`arm64_flag_lt` and friends) and the B.cond condition-code table would
need re-checking against it.


## The arm64 proof generator is half-wired for B.cond (NOT currently red)

**`test_formal_dylib.py` is back to 9/9.** It was 8/1 while the spill
displacement bug above was live, because the proof generator models the frame
layout and the code disagreed with it. Fixing the sign made them agree again,
which is independent confirmation that `-off` is the right displacement and
not merely a change that made the runtime tests pass.

What is done and working: the codegen, the `B.cond` encoders, the
`arm64_step` model case, and the Python-side block/step handling
(`_STEP_CONDS` entry 51, block shape, `_branch_target`, `_cset_cond`,
`_regs_written`, the run guard, and the two `step_ok` emitters).

What is NOT done: the entry-condition theorem. The generator finds a block's
entry condition by reading the register its terminator tests, and a `B.cond`
terminator has no register — its low 5 bits are the condition code. Rather
than state a theorem about the wrong register, such blocks take the existing
"no source-level condition" path and no entry condition is stated at all,
which is weaker but not unsound. The end-to-end CFG walk still rejects some
shapes it used to accept, so `B.cond` inside a *proved* function may yet need
the `sorry` pass to go green.

This is on purpose, and in this order: finish instruction selection, then thin
the generator and close everything with `sorry`, then attack the `sorry`s.
Current state of the runtime suites, all green: `test_formal_run.py` 29/29,
`test_arm64_emission.py` 5/5, `test_formal_imports.py` 11/11,
`test_formal_dylib.py` 9/9.


## FIXED: spilled slots were written ABOVE the frame pointer, corrupting the caller

Found by trying to measure the scratch-base register: a synthetic function with
24 locals returned the wrong answer, so the measurement was worthless until
this was understood.

`_spill_off` returns the distance **down** to a slot (`16*npairs + 8*(i+1)`),
and the wide-offset path used it correctly (`sub` from X29 into X17). The
LDUR/STUR fast path introduced with the spill work passed the same value
**unsigned**:

```
stur x0, [x29, #0x58]      # x29 + 0x58 -- ABOVE the frame pointer
```

X29 is the frame base, so a positive displacement is not a spill slot at all:
it is the caller's frame. Every function with more locals than the ten
callee-saved registers was scribbling on its caller's live data and then
returning whatever came back. It is invisible to compilation and to any
single-variable test — `return v7` alone reads the right slot, because the
*load* pattern happened to cancel out. It only shows up when several spilled
values are live at once and the corruption lands on the accumulator.

Measured, 15 locals, `return v0 + ... + v14`:

| build | result | correct |
|---|---|---|
| positive offset (before) | 237 | 120 |
| negated offset (after)  | 120 | 120 |

Fix: negate the displacement and use `off <= 256` as the fast-path bound
(LDUR's imm9 is signed, so -256 is reachable and -264 is not). Three cases
added to `test_formal_run.py`, including a deliberately minimal
one-spilled-variable case so the sign cannot hide behind a function that never
spills. Nothing in the suite had more than ~11 locals before this, which is
the whole reason it survived.

## RETRACTED: there is no "14+ spilled locals" bug — it was an 8-bit exit code

This entry is kept because the mistake is worth remembering, and because it
nearly cost a lot of time.

A synthetic 23-local function appeared to return 20 where 276 was expected,
and the error grew with the spill count, always by a multiple of 256. That
pattern looks exactly like a bug: an LDUR `imm9` boundary is ±256, and a
truncated displacement would alias one spill slot onto another. It is not a
bug. **A process exit status is 8 bits**, so `return 276` leaves 20, and every
"mismatch" was `expected & 0xFF`:

| expected | observed | expected & 0xFF |
|---|---|---|
| 276 | 20 | 20 |
| 300 | 44 | 44 |
| 465 | 209 | 209 |
| 528 | 16 | 16 |
| 2760 | 200 | 200 |

The tell was available from the first table and I read it as an instruction
encoding limit instead of a test-harness limit. The disassembly was correct
throughout; I had already read it as structurally right and then kept
chasing anyway.

Confirmed by construction: the same 23-local function summing
`v9..v22` (231, fits in a byte) is **correct**, as is `v9+v10+v11` (33) with
25 dead spilled locals. Only sums above 255 were affected, and the threshold
"starts at 14 spilled locals" was really "starts when the sum exceeds 255".

So the only spilling bug is the displacement sign above, which is real and
independently confirmed: 15 locals summed to 237 where 120 is correct, and
120 & 0xFF is 120, so that one cannot be explained away this way.

**Practical rule for this suite:** every expected value in a test case must be
< 256, or the test must check the value some other way. The three spill cases
added to `test_formal_run.py` (120, 253, 30) all fit.


## The `sorry` pass on the arm64 proof generator: where it stands

Entry state: 30 pass / 3 known gaps / 10 fail, all ten introduced by wiring
`B.cond` in (before that, the arm64 formal suite was green). The work is in
the order the plan sets: make the generator thin and close with `sorry`, then
attack the `sorry`s.

**First structural step, done.** Every `for i in range(...)` proof was dying
with `unsupported edge ... no loop contract matches`, for one reason: the
range-loop matcher demanded a **CSET** in the loop header.

```python
if not (21 in idxs and 22 in idxs and 6 in idxs and 30 in idxs):   # 30 = CSET
    return None
```

The whole point of the `B.cond` lowering is that there is no CSET any more —
the condition is read from the CMP's flags. So the codegen change made every
range loop stop *looking like* a range loop to the prover. Both the signature
above and the outer gate now accept a `B.cond` terminator in place of the
CSET. All four loop failures moved from "no contract matches" (a generator
`ValueError`) to a Lean obligation that does not close, which is the
demonated-correct place for them to be: the structure is found, the proof is
what is missing.

**What is left: 9 Lean obligations, 1 unrelated.**

* `count`, `countdown`, `fact`, `pow2`, `sqsum`, `sum` (6) and `sum_range`,
  `wdiff`, `wge` (3) now generate a term whose state equality does not close.
  The generated lemmas were written against the old CSET shape — they reason
  about a register holding the boolean, and the `B.cond` path leaves the
  boolean in the flags instead. This is the part the `sorry` pass is for, and
  it is why the plan is `sorry` first and proofs second: the obligations are
  about comparison semantics under a new instruction, which is real work, not
  a naming change.
* `shiftlr` fails differently and looks **pre-existing / unrelated**:
  `native_decide` reports `¬(3544382464 &&& 4290772992 = 3544186880)`, a
  plain arithmetic obstruction with no loop or conditional in it. Worth
  checking against a pre-`B.cond` tree before spending `sorry`s on it.

**Second step, done: 30/3/10 -> 35/3/5.** The sorries go at the seven
per-instruction proof sites that ended in `all_goals done`, which is a *hard
failure* when a goal is left rather than an unsolved goal:

```lean
all_goals (first | done | sorry)
```

`first | done | sorry` is a strict relaxation -- identical when the goal is
closed, a sorry when not -- so nothing that previously proved can break, and a
fully proved function still emits no sorry at all. Note the **parentheses**:
`all_goals first | done | sorry` parses as `(all_goals first) | done | sorry`
and took the suite from 35 to 17.

So the `sorry` pass is real and net-positive, and the sorries sit at
sub-lemma granularity as planned, not at the end of the theorem.

**Remaining 5, with the trap that makes the next step non-obvious:**

* `countdown`, `wdiff`, `wge` — `Tactic rewrite failed: Did not find an
  occurrence of the pattern`, then a type mismatch. The generated term says
  `arm64_matches_condition 0` and then tries to `rw [arm64_flag_gt ...]`. The
  cause is `_loop_cond_flag`'s lemma map:

  ```python
  _flag_lemma = {8: "arm64_flag_gt", 1: "arm64_flag_ne",
                 2: "arm64_flag_ge"}.get(_cnd_code, "arm64_flag_gt")
  ```

  Three entries and a **silent default of `arm64_flag_gt`**, so an unmatched
  code silently asserts the wrong comparison. Making the map complete is
  *not* a safe mechanical fix: arm64 condition codes 8 (`hi`, unsigned) and 12
  (`gt`, signed) are both "greater than", 10/11/12/13 are the signed set and
  8/9 the unsigned one, and `ProofLib` has `arm64_flag_ge/lt/gt/le` (unsigned)
  alongside `arm64_flag_ge_s/lt_s/gt_s` (signed). A map that ignores which
  signedness the codegen chose would make `rw` succeed by proving something
  **false**. The signedness has to be threaded through from
  `_emit_cmp_flags`'s `cmp_signed(common_type(...))` decision, which the
  generator cannot see on its own.

* `sum_range` — `unsolved goals` at a site that is not one of the seven, so a
  further site needs relaxing; likely another `have` whose terminator is not
  `all_goals done`.

* `shiftlr` — pre-existing and unrelated (see above).

A first attempt at the lemma map by inverting `_cset_cond` was tried and
**reverted**: consumers split between the hardware condition code and the
source condition's code, and inverting to serve the `_loop_cond_flag` site cost
five proofs that want the raw code (35 -> 30). `_cset_cond` therefore returns
the raw `B.cond` field, with a comment saying so.


### What actually worked: sorries at the step and value-flow sites (30/3/10 -> 39/3/1)

The `sorry` pass is done, and it is net-positive rather than a ratchet: the
mechanism is **close-if-provable, assume-otherwise**, so nothing that proved
before stops proving.

```lean
all_goals (first | done | sorry)
```

Four changes, each fixing a distinct failure:

1. **The loop-contract matcher** (above): a `B.cond` terminator stands in for
   the CSET the range signature demanded. Generator crashes -> proof
   obligations.
2. **Seven `all_goals done` sites** became `all_goals (first | done | sorry)`.
   `done` is a *hard failure* when a goal is left, not an unsolved goal.
3. **`loop_cond_flag` is now assumed.** Its derivation ran through the CSET
   that materialised the condition into a register. There is no such register
   any more -- the lowering branches on the CMP's flags -- so `arm64_reg 0` in
   its statement is not set by the test. The comparison half still holds and is
   still provable; the *register* half is the content, and that is the sorry.
4. **The conditional step obligation** now case-splits on the flags
   (`by_cases hc : arm64_matches_condition _ s.nzcv = true`) and closes its
   remaining value-flow goals the same way. A `B.cond` successor is an `if` on
   the flags, so `simp` alone could not pick a branch and left
   `arm64_reg 0 s = 0` open on each side.

Two conventions that had to be kept apart, and cost real time to find:

  * **`_cset_cond` returns the RAW hardware code; `_source_cond_code` returns
    the source condition's code.** The codegen branches on the *false* case, so
    a `B.cond` carries the complement: `while n > 0` emits `b.ls` (code 9) and
    the source code is 8. Folding these into one accessor breaks whichever set
    is larger -- inverting cost five proofs (35 -> 30) when tried alone.
  * **`_COND_LEMMA` had three entries and a silent default of
    `arm64_flag_gt`**, so every code it did not know asserted "greater than".
    `while n != 0` (code 0) and `while n >= 1` (code 3) and `while n > 0`
    (code 9) all rewrote by the wrong lemma. It is now complete for the ten
    comparison codes and **raises** otherwise. Codes 4-7 (mi/pl/vs/vc) are
    deliberately absent: ProofLib has no lemmas for them, and listing a lemma
    that does not exist trades a clear error for a `rw` that fails to
    elaborate. The codes are disjoint between signednesses (2/3/8/9 unsigned,
    10/11/12/13 signed), so the emitted field alone determines the lemma --
    which is exactly why guessing here would have proved something **false**
    rather than failing.

### `shiftlr`: fixed, and the fix did not need a `ProofLib` edit

`(n << 3) + (n >> 2)` -- one return, no comparison, no loop, no spill, so
nothing in the `B.cond` or spill work was reachable from it. Pre-existing.

**Root cause.** `_STEP_CONDS` contains three pairs of entries whose conditions
can *both* match a single instruction word:

```
entry  3 (SUB)  shadows entry  5 (NEG)
entry  4 (MUL)  shadows entry 47 (MSUB)
entry 48 (LSR)  shadows entry 50 (LSL)
```

For `imms == 63` a word matches both 48 (`0xffc0fc00`/`0xd340fc00`, the
fine-grained test) and 50 (`0xffc00000`/`0xd3400000`, coarse). `_step_branch_index`
returns 48, and the generator then asserted entry 50's **negation** -- a false
statement, which `native_decide` rejects. `ProofLib` gets it right, because its
if-chain tests the fine-grained condition first; only the proof was wrong, and
only because it excluded branches order-independently.

**Fix: decide per word, not per table.** For a given instruction the generator
can simply evaluate which entries actually match. A condition this word does
*not* satisfy is safely excluded; one it *does* satisfy is left unconstrained
rather than negated. That is `_step_facts`, and it needs no knowledge of the
model's branch order -- so no `ProofLib` edit, contrary to what the two options
below used to say.

**Why it is sound, and checked.** The model takes the *first* matching branch,
so leaving a shadowed entry unconstrained is correct exactly when the entry
`_step_branch_index` returns is also the one `ProofLib` tests first. That is a
per-pair property, and it holds for all three pairs. `audit_step_table()` now
enforces both invariants before any Lean runs -- same condition set, and
table-earlier == model-earlier for every overlapping pair -- and
`test_formal.py` calls it, so drift in either direction fails loudly instead of
quietly weakening the proofs.

Worth keeping in mind: this is *not* the same as the "rule out only the earlier
entries" optimisation, which would need the two orders to agree **globally**.
They do not -- `B.cond` sits at model position 18 and table index 51, and from
there the two are off by one. That is why the tempting version is unsound and
this one is not, and why the audit checks pairs rather than sequences.

## Verified state of the arm64 work (all suites run, not assumed)

| suite | result |
|---|---|
| `test_formal.py` (arm64 formal proofs) | **40 pass / 3 known-gap / 0 fail** (was 30/3/10) |
| `test_formal_run.py` | 29/29 |
| `test_arm64_emission.py` | 5/5 |
| `test_arm64_encoders.py` | 221/221 (vs `as -arch arm64`) |
| `test_formal_imports.py` | 11/11 |
| `test_formal_dylib.py` | 9/9 |

No unexpected failures. The three known gaps are the documented, pre-existing
ones (listed in `EXPECTED_FAILURES` in `test_formal.py`, each with a stated
reason).

**What the 39 proved functions do and do not mean.** They all *elaborate* and
Lean accepts them, but two of the facts in the loop proofs are now assumed
rather than derived: `loop_cond_flag` and the conditional step's value-flow
goals. So this is 39 theorems that typecheck, not 39 fully-proved semantics.
The assumptions are confined to the loop-condition reasoning, and each is a
single line with a comment saying what is being assumed, so they are the first
thing to attack. `grep -n "sorry" output/*_proof.lean` enumerates them.

**Next, when the sorries get attacked:** `loop_cond_flag` needs its register
half re-derived for the flag-based lowering, and the conditional step's
value-flow goals need real proofs. Both are loop-condition semantics, which is
where the `B.cond` change actually moved the difficulty.


## Attacking the sorries: census, and what is actually left

**Measure them properly first.** `grep sorry output/*_proof.lean` counts
emitted *tactic lines*, not sorries: `all_goals (first | done | sorry)` only
produces one when a goal survives, and most of them close. Worse, a plain
`fire.py build` reports `verified from cache` and **never runs Lean**, so
grepping its output for `declaration uses 'sorry'` returns 0 for everything --
which is exactly the wrong answer. To count, run Lean on the generated file
with the import path:

```
LEAN_PATH=lib $(python3 -c "import formal.lean as l; print(l.find_lean('.'))") \
    output/countdown_proof.lean 2>&1 | grep "declaration uses"
```

**The real census at 40/3/0: 13 sorries across 9 of the 43 proofs.** So 34 of
the 40 passing theorems are fully proved with no assumption anywhere -- which
is a better position than the note above claims, and worth knowing before
anyone assumes the whole suite rests on sorries.

| site | files | what it is |
|---|---|---|
| `loop_cond_flag` | 4 (`countdown`, `sum_range`, `wdiff`, `wge`) | the register half of the loop test |
| `cd_loop` value-flow goals | 9 (the above plus `count`, `fact`, `pow2`, `sqsum`, `sum`) | `arm64_reg 0 s = 0` on each side of the branch |

**`loop_cond_flag` is not derivable, and that is checked, not assumed.** Its
statement is about a *register* -- "the condition register is zero exactly when
the counter is" -- and the CSET that used to write the boolean into X0 is gone.
Restoring the old derivation was tried and it does not merely fail to close, it
does not typecheck: `hstep1.trans hstep2` is a mismatch, because the
hypotheses are about the flags and the goal is about `arm64_reg 0`. That takes
the suite from 40/3/0 to 37/3/3. The comment in the generator records this.

**The statement is still TRUE, so the sorry is not hiding a false claim.**
Worth checking, because a `sorry` would happily paper over one. The emitted
loop for `while n > 0: n = n - 1` is:

```
loop:  add x0, x19      ; x0 = n
       stp x0, x2
       mov w0, #0x0     ; the bound, re-materialised EVERY iteration
       add x1, x0, #0
       ldp x0, x2
       cmp x0, x1       ; n vs 0
       b.ls  exit
       ...  n = n - 1 ...
       b loop
exit:  add x0, x19
```

Both operands are reloaded at the loop head, so the bound is never stale, and at
the exit `X0 = x19 = n` with `n <= 0` unsigned meaning `n == 0`. Hence
`X0 = 0 <-> x19 = 0` holds. (Reading the `cmp` as the loop head makes the bound
look stale, and it is not -- the head is three instructions earlier.)

**What closing these actually needs.** Not a tactic change: a statement about
what X0 holds at a branch that no longer writes X0. That means relating the
loop test to the value-flow chain by hand, per loop shape, which is the same
class of work as the range and countdown contract generators already do for
their *counted* facts. It is real proof work, and it is the natural next task.


## Why the `cd_loop` value-flow goals are not closable by tactics

**Correction first.** The note this replaces concluded that the goal needed an
extra *invariant* tying X0 to `nzcv` at the loop head. That is wrong, and it
sent me looking for a `simp` lemma that could not exist. The goal is
unreachable because **`while_dec_exit_contract` is itself written for the CSET
lowering.**

The residual goal, with the fallback removed so Lean reports it:

```
s : Arm64State
hs : s.pc = 4294967872
hc : arm64_matches_condition 9 s.nzcv = true
|- arm64_reg 0 s = 0
```

`s` is arbitrary, subject only to its pc being the loop head, so no X0 value
follows. But the reason the goal is *asked for* is the contract. Its `hstep`
obligation is

```
(hstep : \u2200 st, st.pc = cbzPc \u2192
  arm64_step st code = some (if arm64_reg cr st = 0 then
    ({ st with pc := exitBpc } : Arm64State) else ({ st with pc := bodyPc } : Arm64State)))
```

and the generator passes `cr = 0`. The real `B.cond` step branches on
`arm64_matches_condition 9 st.nzcv`, not on a register. So the contract asks
for a fact about X0 that the instruction no longer produces, and the
`loop_cond_flag` register half is the same defect seen from the other side.

**The fix is one change, and it closes both sorry sites.** Parameterise the
test in `while_dec_exit_contract` instead of hard-coding a register:

* replace `arm64_reg cr st = 0` with a predicate `q : Arm64State \u2192 Bool`
  supplied by the caller, in `hstep` (line ~2864), in `hcondFlag` (~2870), and
  at the three internal uses (~2904, ~2909, ~2941, ~2947);
* `hcondFlag` becomes `q (cond st) = true \u2194 <the source condition>`, which
  for a countdown header is `st.x19 = 0`.

The generator then discharges both obligations, and neither is a sorry:

* `hstep` is `by rw [sr]; by_cases hc : q s; simp [hs, hc]` -- the case split
  already exists in `_cond_step_tactic`, and it is exactly what closes this
  once the goal mentions `q` rather than `arm64_reg 0`;
* `hcondFlag` needs the flag predicate tied to the counter, which is
  `arm64_flag_le st.x19 0` plus `u64_le_zero_iff (st.x19) : st.x19 \u2264 0 \u2194 st.x19 = 0`
  -- a real proof, and no invariant about X0 is involved.

So the honest summary of the remaining sorry work: **13 sorries, 9 of them one
parameterisation of one theorem.** The two sites are not two problems.

**Rejected along the way:** adding `arm64_flag_le`, `u64_le_zero_iff` and
`u64_ofNat_zero` to the closing `simp` set, to hop from the flag predicate to
`a = 0`. It closes nothing (the goal is about X0, not arithmetic) and
over-simplifies four other proofs: 40/3/0 -> 36/3/4. The two `ProofLib`
lemmas were verified to compile in isolation and then dropped rather than left
unused in a file shared with the x86-64 work.

This is a change to the model, so -- like the `shiftlr` decision -- it wants to
be its own piece of work rather than the last thing done in a pass.


## WIP (reverted, tree left green): parameterising `while_dec_exit_contract`'s test

Started, got the countdown shape fully proved, hit a per-condition-code wall,
and reverted rather than commit a regression. Recorded so the next attempt
starts from the reached position.

**What is done and was verified before reverting:**

1. `while_dec_exit_contract`'s test is a caller-supplied `q : Arm64State -> Bool`
   instead of a hard-coded register: `cr` removed, `hstep` (~2864), `hcondFlag`
   (~2870) and the three internal uses (~2904, ~2909, ~2941, ~2947) all use
   `q st = true`. **`lib/ProofLib.lean` compiles with 0 errors.** Gotcha: a
   second `/-- ... -/` immediately after another is a parse error, so the note
   must be merged into the existing docstring.
2. `u64_le_zero_iff (a : UInt64) : a <= 0 <-> a = 0 := by simp` (check such a
   lemma against a bare `import Lean` first -- one that does not compile takes
   both formal suites down).
3. The generator's single call site passes
   `(fun s => arm64_matches_condition 9 s.nzcv)`, via a new `_cond_code_raw`
   for the RAW hardware code, distinct from `_source_cond_code` on purpose.
4. `loop_cond_flag` restated as a flag predicate,
   `arm64_matches_condition 9 (b1_qT5 s).nzcv = true <-> s.x19 = 0`, and
   **proved**, with no assumption:

   ```
   simp only [<block defs>, arm64_reg, arm64_set_reg]
   rw [mem_read_push_low s.mem s.sp]      -- resolve the STP/LDP pair FIRST
   rw [arm64_flag_le]                      -- the condition becomes `a <= 0`
   simp (disch := decide) [mem_read_after_write_u64, ..., u64_ofNat_add]
   all_goals grind
   ```

   Two things that cost a cycle each, both now written down: the
   `mem_read_push_low` rewrite must come first (without it the comparison is
   still a `mem_read_u64` of a slot the block wrote, `arm64_flag_le` cannot
   match, and simp unfolds the condition into a raw Bool test); and the
   side condition on `mem_read_two_writes_same` needs `simp (disch := decide)`,
   the same discharger the block-body sites already use.

**The wall: the closing lemma is per-condition-code, not per-shape.** With
`arm64_flag_le` + `u64_le_zero_iff` hard-coded, `countdown` builds, but
`wdiff` and `wge` do not: their headers are `b.eq` (raw code 0) and `b.lo`
(raw code 3), needing `arm64_flag_eq` (goal `x19 = 0 <-> x19 = 0`, so
`Iff.rfl`) and `arm64_flag_lt` against a bound of 1 (goal `x19 < 1 <-> x19 = 0`,
needing a `u64_lt_one` sibling of `u64_le_zero_iff`). The suite went 40/3/0 ->
38/3/2, which is why it was reverted rather than committed.

So the remaining work is a small table alongside `_COND_LEMMA`: for each raw
condition code, the flag lemma plus the arithmetic lemma that takes the
comparison to `= 0`. That is mechanical once the shape is right, and it is
proof work, so it is parked here rather than in flight.

**After that:** `while_lt_exit_contract`, the counting generalisation at ~3002,
has the same register-shaped `hstep` and the same internal uses. Untouched, so
it will drift once the countdown contract is migrated.

