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

| | before | after |
|---|---|---|
| encoders | 52 | 69 |
| covered | 86.2% | **92.0%** |
| genuinely uncovered | 11.5% | **5.7%** |

### Re-measured 2026-10-02, because a survey nobody re-runs is a guess

`python3 tools/arm64_insn_audit.py` still works and its numbers are the tree's:

```
encoders in formal/arm64.py : 75 (58 base mnemonics)
disassembled               : 4026231 instructions over 420 distinct mnemonics, 200 binaries
covered by an encoder      : 3706716 (92.1%)
excluded by decision       : 91826 (pointer auth, udf, hints — see docstring)
genuinely uncovered        : 227689 (5.7%)
```

Six more encoders and a tenth of a percent of coverage since the table above was
written, with the uncovered share unmoved — which is the useful part: the
additions went where the audit said they mattered (the ranked uncovered list is
still dominated by NEON, FP and the cryptographic extensions, none of which this
backend has a use for on a target that is int-only, `formal/types.py` being the
authority on that). **Not a bug and no bug doc: this file is the survey, and it
stays because the answer is not guessable.**

## What was added, in the order the audit said it mattered

- **`B.cond`, all 14 conditions** — by far the biggest single gap (~154k
  occurrences). `if a < b` was `cmp` + `cset` + `cbz` + a branch: three
  instructions, one materialising a boolean the branch immediately reads back.
  Now wired at every site; see
  `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` for the two bugs that wiring
  uncovered (the displacement never patched, and `for` loops having no exit).
- **`CSEL` / `CSINC` / `CSINV` / `CSNEG`** (~40k) — a conditional *expression*
  should not become a branch. With Rn = Rm = XZR, CSEL is exactly CSET, which
  is how the existing `encode_cset_*` is now expressed.
- **`TBZ` / `TBNZ`** (~75k) — `if x & (1 << n):` was a mask, a compare and a
  branch. **Bits 0-31 only**: the architectural b40 form relocates imm14, and
  encoding that from memory of the spec is how you get a branch to the wrong
  address, so bits >= 32 raise instead.
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

## Two test-design lessons from this work

Both cost real time, and both are the kind of gap a green suite hides.

1. **Comparing instruction bytes is not comparing instructions.**
   `test_arm64_encoders.py` proves every encoder byte-for-byte against
   `as -arch arm64` (221/221). It therefore *cannot* see a missing
   **relocation** — and `Assembler.resolve()` had no `B.cond` case, so
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

## Landed alongside: `dylib_syms` on the arm64 constructor

`ARM64Codegen.__init__` did not accept `dylib_syms` while `formal/build.py`
passed it, so the mismatch was a **runtime** failure on the branch that reached
the constructor — invisible at import time, and a build-only check that never
reached it would still have been green. Fixed: accepted at
`formal/arm64_codegen.py:423`, stored at `:481`, consumed at `:2960` via
`emit_extern_bl`.

Worth keeping as a test-shape note rather than a code note: `_make_codegen` is
shared by both backends, so a keyword added for one of them breaks the *other*
at runtime. `test_x86_64_examples.py` catches that class because it builds the
same example through **both** backends — which is the only reason this was
caught before it reached `--backend=arm64` users.
