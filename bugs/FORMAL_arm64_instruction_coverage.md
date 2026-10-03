# FORMAL_arm64_instruction_coverage: the arm64 encoder survey, and what wiring the new instructions actually bought

**Status: the survey is current as of 2026-10-03 and has been re-measured twice
on this tree — once for the method and once for the two largest gaps. `TBZ` and
`TBNZ` are now WIRED (encoder, machine model, proof tables, and a lowering that
emits them), which moved 74,682 of the 4,026,231 disassembled instructions from
"excluded by decision" into "covered". The file stays a survey, for the reason
below.**

Preserved from the root `BUG.md` (deleted 2026-09-26) so the survey and its
measurements are not lost. Not a bug report: a **survey**, kept because the
answer is not guessable and the tooling to re-derive it should not be written
twice. Bugs found *by* this work have their own documents — see
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md` for the spill-displacement sign
and the loop-exit bugs, `FORMAL_arm64_known_proof_gaps.md` for the three
unproved examples, and `FORMAL_arm64_bit_test_branch_is_not_provable.md` for the
one gap the TBZ/TBNZ wiring left behind.

## Method

`tools/arm64_insn_audit.py` answers "what can the codegen not emit, weighted by
how often a compiler actually emits it". Counting the encoder table is a
different question: this backend had **52 encoders and still could not express a
single conditional branch on a comparison's flags.**

- encoder inventory from `formal/arm64.py`
- real instruction mix by disassembling 200 system binaries (4.0M instructions,
  420 distinct mnemonics)
- rank the difference

Pointer-authentication instructions (`pacibsp` and friends, ~92k) are excluded
**by decision, and the exclusion is printed** — a backend with nothing to
authenticate has no use for them, and hiding that in a filter would be
dishonest accounting.

| | before | after | after, counting only EMITTED encoders (2026-10-03) | …and after TBZ/TBNZ were WIRED (2026-10-03, below) |
|---|---|---|---|---|
| encoders | 52 | 69 | 60 of 75 in the table are emitted by a lowering | **62** of 75 |
| covered | 86.2% | **92.0%** | **89.1%** | **90.9%** |
| genuinely uncovered | 11.5% | **5.7%** | **5.7%** | **5.7%** |

The third column is the survey asked the question it should have asked from the
start, and the middle one is what this file reported until 2026-10-03. The
"genuinely uncovered" row is the invariant across all three, which is the thing
worth knowing: the additions went where the audit said they mattered, and what
the method change moved was the boundary between "covered" and "excluded", not
the work.

### Re-measured 2026-10-03, and the METHOD changed: an encoder is not an
### instruction until something emits it

The 2026-10-02 numbers above were read off the encoder TABLE. `tools/arm64_insn_audit.py`
now asks a second question of every encoder — **is it referenced by any lowering
in `formal/`?** — and counts only those as coverage, printing the rest by name:

```
encoders in formal/arm64.py : 75 (58 base mnemonics)
emitted by a lowering       : 60 (47 base mnemonics) — an encoder nothing CALLS is not an instruction any image contains
disassembled               : 4026231 instructions over 420 distinct mnemonics, 200 binaries
covered by an encoder      : 3586069 (89.1%)
excluded by decision       : 212473 (pointer auth, udf, hints, and encoders with no caller — see docstring)
genuinely uncovered        : 227689 (5.7%)

encoders no lowering emits (15), by name:
  encode_blr_xn  (blr)          encode_movn_xd_imm  (movn)
  encode_cmn_xn_xm  (cmn)       encode_str_xt_sp_imm  (str)
  encode_cset_wd_cond  (cset)    encode_strh_wt_wn_imm  (strh)
  encode_csinc_xd_xm_cond  (csinc)   encode_subs_xd_xn_xm  (subs)
  encode_csinv_xd_xm_cond  (csinv)   encode_tbnz_xn_bit  (tbnz)
  encode_csneg_xd_xm_cond  (csneg)   encode_tbz_xn_bit  (tbz)
  encode_ldp_xn_xt_sp  (ldp)     encode_tst_xn_xm  (tst)
  encode_ldr_xt_sp_imm  (ldr)
```

**The uncovered share did not move — 5.7%, the same 227,689 instructions — and
that is the result.** What moved is 120,647 instructions from "covered" to
"excluded by decision", and they are all cases where the encoder exists, the
byte-exact test passes, and no image can contain the instruction. `tbnz` (49,645
occurrences) and `tbz` (25,037) were the two largest single entries in the gap
list all along and were being reported as covered; `tst`, `cmn` and `strh` are
the same. Under-reporting coverage is the same defect as over-reporting it —
both are the survey answering a question nobody asked — and the gap list is what
somebody works through next.

**One mapping bug fell out of it.** `encode_blr_xn` matched neither the `bl` nor
the `br` family, so its base came out as `blr_xn` — a string no disassembler ever
prints — and `blr` was reported as a gap the backend can close in one line.
`blr` is in the family table now, and `test_arm64_encoders.py` fails if any
`encode_*` maps to no declared mnemonic.

### The two largest gaps are now closed: TBZ / TBNZ are WIRED (2026-10-03)

`tbnz` (49,645) and `tbz` (25,037) were the two largest single entries in the gap
list, 1.85% of every instruction a real compiler emits, and the entry above is
right about why they were unreached: **encoded, byte-exact, and called by
nothing**. They are now emitted, and the re-measurement is:

```
encoders in formal/arm64.py : 75 (58 base mnemonics)
emitted by a lowering       : 62 (49 base mnemonics)   [was 60 (47)]
covered by an encoder       : 3660751 (90.9%)           [was 3586069 (89.1%)]
excluded by decision        : 137791                    [was 212473]
genuinely uncovered        : 227689 (5.7%)             [unchanged]
```

The 74,682-instruction move is `25_037 + 49_645` exactly. **"Genuinely uncovered"
does not move and is not supposed to**: it counts instructions this backend has
no encoder for, and these two had encoders — they were in the other column, which
is the whole point the 2026-10-03 method change made.

What landed, and it is four things rather than one because an encoder is not an
instruction:

1. **The lowering.** `_emit_branch_unless_bit_test`, which is
   `_emit_branch_unless`'s first arm: `if x & (1 << n):` becomes one `TBZ` and
   `if not (x & (1 << n)):` one `TBNZ` — different instructions, because the
   polarity inverts which way the branch leaves. `x & 8` and `8 & x` are the same
   question, `x & 0xff` is not a bit test at all (eight bits, not one) and falls
   through to the general path, bit 40 is declined because the encoder refuses
   the b40 form rather than encoding it from memory of the spec, and an operand
   that needs a call is declined because the bit test is only cheaper when the
   operand is already a word.
2. **`Assembler.resolve()`'s relocation for them.** This is the half that is
   invisible to a byte comparison, and getting it wrong was the actual
   development cost: with no arm at all, imm14 stayed 0 and every bit test
   branched to ITSELF (`if x & 8:` hung the program) with
   `test_arm64_encoders.py` 424/424 green throughout; with the CBZ family's
   preserve-mask `0xff00001f`, bits 19..23 — the BIT NUMBER — were cleared and
   every test became `tbz w0, #0`, which built, ran, and printed `0 0` where the
   source says `1 0`. The mask is `0xfff8001f`. Both failures are the lesson in
   §"Comparing instruction bytes is not comparing instructions" happening again,
   and `test_arm64_emission.py`'s self-branch check and per-case BIT assertion are
   what caught them.
3. **The machine model.** `lib/ProofLib.lean`'s `arm64_step` gains the two
   cases, beside the other pc-only branches and before every data-processing
   case; `0x36`/`0x37` are the b5 test-bit encodings and every mask above them
   was checked against them. imm14 and not imm19, sign-extended from bit 13 of
   its own field. **`lib/ProofLib.lean` typechecks with them** — verified through
   `formal/lean.py::ensure_library`, which is the only thing in this list that is
   a measurement rather than a reading.
4. **The proof tables.** `_STEP_CONDS` entries 52/53 (APPENDED, so no
   hard-coded index moves), the `_step_rhs` and `_step_rhs_generic` right-hand
   sides, the block scanner treating them as the `cbz` kind, and `loop_test`
   answering for them. `_step_facts` decides every other entry's condition PER
   WORD, so adding two entries adds two `have` lines to every generated lemma and
   renumbers nothing — which is why this was cheap and the MODEL was not: adding
   a branch to `arm64_step` required `hne_tbz` / `hne_tbnz` in each of the 18
   `work_step_*` theorems that negate every branch before their own, and
   `lib/ProofLib.lean` did not typecheck until all 18 had them.

**What is NOT done, and it is one arm.** An `if` whose condition is a bit test
**compiles, runs, and answers CPython**, and cannot be *proved*: the generator
derives a branch's source-level proposition out of the cset that wrote the tested
register, and TBZ/TBNZ write no register and set no flags. The generator refuses
rather than emitting an `hcond` about the wrong thing, which is the correct
failure. `bugs/FORMAL_arm64_bit_test_branch_is_not_provable.md` has the
measurement, the site, and the next step — and it is why
`formal/examples/bittest.mojo` is not committed with this: the example fails
today and a failing example with no `EXPECTED_FAILURES` entry is the wrong shape.

**The six encoders of 2026-10-02 are still six.** The genuinely-uncovered list
is still dominated by NEON, FP and the cryptographic extensions, none of which
this backend has a use for on a target that is int-only (`formal/types.py` is the
authority on that). **Not a bug and no bug doc: this file is the survey, and it
stays because the answer is not guessable** — more so now, since the answer has
moved twice already (the 2026-10-03 method change, and the TBZ/TBNZ wiring).

## What was added, in the order the audit said it mattered

Read this list as what was ENCODED; the entries marked † are encoded and
**not emitted**, which the 2026-10-03 measurement above is how we know, and
which is the one thing in this file that was wrong before. The `TBZ`/`TBNZ` entry
was one of them until 2026-10-03 and no longer is; `CSEL`'s three neighbours
(`csinc`, `csinv`, `csneg`) are the remaining half of that, and `csinc` is still
3,014 occurrences of gap.

- **`B.cond`, all 14 conditions** — by far the biggest single gap (~154k
  occurrences). `if a < b` was `cmp` + `cset` + `cbz` + a branch: three
  instructions, one materialising a boolean the branch immediately reads back.
  Now wired at every site; see
  `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` for the two bugs that wiring
  uncovered (the displacement never patched, and `for` loops having no exit).
- **`CSEL` / `CSINC` / `CSINV` / `CSNEG`** (~40k) — a conditional *expression*
  should not become a branch. With Rn = Rm = XZR, CSEL is exactly CSET, which
  is how the existing `encode_cset_*` is now expressed. **† `CSEL` only:**
  `arm64_codegen.py` emits `encode_csel_xd_xm_cond` at six sites and nothing in
  `formal/` references `csinc`, `csinv` or `csneg` — so a ternary is a CSEL, and
  the other three are a table nobody calls.
- **`TBZ` / `TBNZ`** (~75k) — `if x & (1 << n):` was a mask, a compare and a
  branch. **Bits 0-31 only**: the architectural b40 form relocates imm14, and
  encoding that from memory of the spec is how you get a branch to the wrong
  address, so bits >= 32 raise instead. **BOTH EMITTED as of 2026-10-03** — the
  † is gone, and "§The two largest gaps are now closed" above is what replaced
  it: the lowering, the relocation, the machine model and the proof tables. A bit
  test is one instruction now, and the mask this entry describes as removed is
  gone with it.
- **`LDUR` / `STUR`** (~45k) — unscaled access, which in practice means the
  NEGATIVE displacement a scaled-offset load cannot express. This is the
  instruction whose emission carried a real bug; the sign writeup is in the
  companion doc.

## What it bought, measured rather than assumed

A benchmark mixing a ternary, `and`, `or` and fourteen spilled locals:

- **997 → 225 instructions** (~77% fewer), same answer.
- `CSEL` with plain-local arms is 4 instructions and touches no stack at all.
- Large immediates (>4095) fold into one shifted add rather than a chain of
  33: `mov` + `sub` + access became one instruction. This was the single
  largest codegen win in the project.

The part that is **not** a win is in the companion doc: the scratch-base
register, measured and rejected.

## Three test-design lessons from this work

All three cost real time, and all three are the kind of gap a green suite hides.

1. **Comparing instruction bytes is not comparing instructions.**
   `test_arm64_encoders.py` proves every encoder byte-for-byte against
   `as -arch arm64` (424/424 as of 2026-10-03). It therefore *cannot* see a
   missing **relocation** — and `Assembler.resolve()` had no `B.cond` case, so
   `imm19` stayed 0 and every conditional branch pointed at itself. A fully
   green encoder suite coexisted with a compiler that hung on any false
   comparison. `test_arm64_emission.py` now asserts that no branch resolves to
   its own address, and that check was verified to fail when the fix is removed,
   so it is not vacuous.
2. **Every expected value must fit in a byte.** A process exit status is 8
   bits. Comparing one against a wider sum produced a convincing phantom
   "14+ simultaneously-spilled locals are miscompiled" bug, complete with a
   plausible mechanism (an LDUR `imm9` boundary) and a table of numbers. Every
   "mismatch" was `expected & 0xFF`. The real spilling bug it was chasing was
   a *sign* error, one column away in the same table.
3. **An encoder with no caller is not an instruction either** — the same lesson
   one step earlier, and the reason the audit's method changed above. 15 of the
   75 encoders are referenced nowhere outside their own definition, so a survey
   that reads the table overstates coverage by 120,647 of 4,026,231 real
   instructions and hides the two largest genuine gaps (`tbnz`, `tbz`) inside
   its covered set. The encoder suite cannot see it — those 15 are byte-exact
   and green — so `tools/arm64_insn_audit.py` now separates "in the table" from
   "emitted by a lowering", prints the difference by name, and
   `test_arm64_encoders.py` asserts the DIRECTION (covered bases come from
   encoders something references) rather than a count, because landing an
   encoder before its lowering is the ordinary order of work here. That check
   was verified to fail against a copy of the audit that read the table again.

## Landed alongside: `dylib_syms` on the arm64 constructor

`ARM64Codegen.__init__` did not accept `dylib_syms` while `formal/build.py`
passed it, so the mismatch was a **runtime** failure on the branch that reached
the constructor — invisible at import time, and a build-only check that never
reached it would still have been green. Fixed: accepted at
`formal/arm64_codegen.py:558`, stored at `:679`, consumed at `:5011` via
`emit_extern_bl` (line numbers as of 2026-10-03; the shape is what the note is
for, and the numbers drift with every edit above them).

Worth keeping as a test-shape note rather than a code note: `_make_codegen` is
shared by both backends, so a keyword added for one of them breaks the *other*
at runtime. `test_x86_64_examples.py` catches that class because it builds the
same example through **both** backends — which is the only reason this was
caught before it reached `--backend=arm64` users.
