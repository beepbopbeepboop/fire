# FORMAL_arm64_instruction_coverage: the arm64 encoder survey, and what wiring the new instructions actually bought

Preserved from the root `BUG.md` (deleted 2026-09-26) so the survey and its
measurements are not lost. Not a bug report: a **survey**, kept because the
answer is not guessable and the tooling to re-derive it should not be written
twice. Bugs found *by* this work have their own documents — see
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md` for the spill-displacement sign
and the loop-exit bugs, and `FORMAL_arm64_known_proof_gaps.md` for the three
unproved examples.

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

| | before | after | after, counting only EMITTED encoders (2026-10-03) |
|---|---|---|---|
| encoders | 52 | 69 | 60 of 75 in the table are emitted by a lowering |
| covered | 86.2% | **92.0%** | **89.1%** |
| genuinely uncovered | 11.5% | **5.7%** | **5.7%** |

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

**The six encoders of 2026-10-02 are still six.** The genuinely-uncovered list
is still dominated by NEON, FP and the cryptographic extensions, none of which
this backend has a use for on a target that is int-only (`formal/types.py` is the
authority on that). **Not a bug and no bug doc: this file is the survey, and it
stays because the answer is not guessable** — more so now, since the answer has
moved once already.

## What was added, in the order the audit said it mattered

Read this list as what was ENCODED; the two entries marked † are encoded and
**not emitted**, which the 2026-10-03 measurement above is how we know, and
which is the one thing in this file that was wrong before.

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
  address, so bits >= 32 raise instead. **† Neither is emitted**: a bit test is
  still `and`/`cmp` + a branch, so the mask the doc describes as removed is
  still there. The two are the largest entries in the real gap list
  (49,645 + 25,037), which is the honest way to size the work.
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
