# FORMAL_the_arm64_step_table_audit_read_a_branch_out_of_a_comment: twelve red
# examples nobody could see, because the suite raised before it generated one

**Area:** FORMAL / proof generation — `formal/arm64_proof_gen.py`'s
`audit_step_table`, and the census it was hiding.
**Status: the AUDIT is fixed (same commit). Of the twelve examples it was
hiding, ELEVEN now generate and one (`sum_range`) still refuses — and that
refusal belongs to another worker's claim. The remaining measurement is whether
Lean accepts the eleven; see §4.1.** Filed 2026-10-03 on `work/formal16-2`,
refreshed 2026-10-04.

## 1. What was wrong, and why it is a hole rather than a red test

`audit_step_table` compared `_STEP_CONDS` against `lib/ProofLib.lean` by running
an **unanchored** `re.findall` for `insn &&& (mask)) = (base)` over the body of
`arm64_step`. The body includes the comments above each branch, and the comment
above the TBZ case quotes its own condition:

```lean
  -- data-processing case, because `(insn &&& 0xff000000) = 0x36000000` is
  -- specific (top byte 0x36 is the test-bit space and nothing else in A64) and
```

So the model list came out **one entry longer** than `_STEP_CONDS`, the two
lists' symmetric difference was **empty in both directions**, and the
comparison — which tested `sorted(model) != sorted(table)` — raised:

```console
$ python3 test_formal.py bittest
AssertionError: step table and ProofLib disagree: only in ProofLib [],
only in _STEP_CONDS []
```

`test_formal.py` calls `audit_step_table` **before** it compiles anything, so
**the whole arm64 proof suite had not run since that comment landed** — 49
examples, including the two Lean-checking jobs the gate runs. `check_step_conds`
was unaffected and passing the whole time, because it reads the same question
line by line with an anchored pattern (`_decoder_branch_conds`); that is why
nothing caught it.

Measured, on this tree and on its parent: identical failure, both.

**The fix is de-duplication, not a reworded comment.** `audit_step_table` now
calls `_decoder_branch_conds(src)` — the same reader `check_step_conds` uses —
so the two audits cannot disagree about what a branch condition is, and a
comment that quotes the condition it is reasoning about stops being a branch. A
comment fix would have left the two readers in place.

## 2. What it was hiding: twelve red examples, in four signatures

With the audit passing, the suite runs for the first time since 2026-10-03:

```console
$ python3 tools/memslot.py --gb 32 --label tf -- python3 test_formal.py -j 6
Results for arm64 formal proofs: PASS=33 KNOWN-GAP=4 FAIL=12
proof census: 0 admitted `sorry` in the generated file, in 0 of 33 proof(s) checked
```

| # | examples | the failure, as it prints |
|---|---|---|
| 1 | `count`, `fact`, `pow2`, `sqsum`, `sum` (5) | a Lean `Nat`/type mismatch beginning `t64.ofNat 4294968008 - (UInt64.ofNat 4294968008 % 4096 - ((if False then … else …) * 4096 + UInt64.ofNat 8)).toNat` — an ADRP page computation, so the family is "a program whose first instruction is an address materialisation" (`print("hi")` is the shape the file's own comment says exposed this once already) |
| 2 | `sgt8`, `sle8`, `ug8` (3) | a 30-field `Arm64State` structure literal mismatch printed as `14✝⁴, x15 := x15✝⁴, …` — the TYPED model's truncator shape against the untyped one, i.e. the `t8s`/`t8u` family `formal/types.py`'s `lean_trunc_defs` emits |
| 3 | `both`, `either` (2) | `build: proof check failed: ProofLib …` — the library itself, not the generated file |
| 4 | `sum_range`, `wdiff` (2) | a generator `ValueError` out of `emit_block` — `unsupported cbz taken continuation to …` and `unsupported edge to … (loop back-edge / continuation; no loop contract matches)`, i.e. the LOOP family |

**All twelve are pre-existing.** Verified by measurement, not by argument: the
same twelve, no more and no fewer, fail on this tree's parent with the audit fix
applied and nothing else (`diff` of the two failure lists is empty). The
`KNOWN-GAP=4` are `countdown`, `fib`, `subscript_var`, `wge` — the four entries
`test_formal.py`'s `EXPECTED_FAILURES` still carries, so the harness's stale
check is satisfied and the count is the table's.

## 3. What is NOT claimed, and who the remainder belongs to

* **Not diagnosed here.** Each signature above is a census entry, not a
  diagnosis: four Lean-side families is more than this change's budget, and
  guessing at a reason for an `expect=` marker is exactly the fabrication
  `CLAUDE.md`'s marker rules exist to prevent. So nothing is marked.
* **The stale authority.** `bugs/FORMAL_arm64_known_proof_gaps.md` says
  "`EXPECTED_FAILURES` remains the authority on whether these are still gaps"
  and reports `41 pass / 4 known-gap / 0 fail` measured 2026-10-01 — which is
  both inconsistent with its own "six gaps" sentence and 12 failures away from
  today's measurement. That doc is `work/formal16-3`'s claim, and its census is
  what should be re-measured now that the suite runs again.
* **Not a gate regression.** `formal` was red before this change and is red
  after it; the difference is that it now says why.

## 4. The exact next step

**Step 1 is DONE and it is pinned; step 2 is done and its owner is named; step
3's premise is measured and the measurement says the library is fine. What is
left is §4.1, and it is a sequence of Lean runs rather than a diagnosis.**

Measured 2026-10-04, `compile_formal(prove=True, check=False)` on arm64 for every
one of the twelve, plus one Lean run for `wdiff`:

| the twelve | 2026-10-03 | 2026-10-04 |
|---|---|---|
| `count` `fact` `pow2` `sqsum` `sum` | Lean type mismatch on an ADRP page computation | **GENERATE** |
| `sgt8` `sle8` `ug8` | a 30-field `Arm64State` literal mismatch | **GENERATE** |
| `both` `either` | `build: proof check failed: ProofLib` — the LIBRARY | **GENERATE** |
| `sum_range` | a generator `ValueError` out of `emit_block` | **still refuses**: `ValueError: unsupported cbz taken continuation to 0x100000330` |
| `wdiff` | a generator `ValueError` out of `emit_block` | **PASSES** — `test_formal.py -j 1 wdiff` gives `PASS=1 KNOWN-GAP=0 FAIL=0`, `proof census: 0 admitted sorry` |

**Eleven of the twelve reach a proof file and one does not.** `sum_range`'s
refusal belongs to `bugs/FORMAL_sum_range_generation_refused_and_it_is_not_an_expected_failure`,
another worker's claim, which names the cause exactly (the loop's back edge is a
CONDITIONAL branch, so `emit_block`'s `tgt_bi is None or tgt_bi in path` fires)
and cites a `wdiff`-loop-contract doc as "one arm away" — that doc has since been
fixed and DELETED, and `wdiff` passing today is the measurement of it. So
§4's original step 2 is closed by someone else and nothing here touches either
file.

Family 3's premise — "either a `.olean` is stale against `lib/*.lean` or the
library stopped typechecking" — is measured FALSE by the same table: both stems
generate, which they could not do against a library that does not typecheck, and
`wdiff`'s Lean run typechecked a proof that imports it.

**The census is pinned rather than recorded**, in
`test_formal_call_proof_gen.py::TestTheRecursionFamiliesStillGenerate`: each of
the eleven still generates AND writes a file carrying the arm64 end-to-end
theorem `<fn>_compiles_correctly_universal`; `sum_range` still refuses and its
message still carries the PREMISE (`cbz taken continuation`) rather than the
layout's address; and every pinned refusal has a bug doc naming it, because a row
that pins a refusal without naming its owner keeps a stale claim alive after the
fix lands. That file's rule is GENERATION ONLY, no Lean, so the pin costs 0.5 s
and runs every time.

### 4.1 What is left, and it is a sequence of Lean runs

**Whether Lean ACCEPTS each of the eleven.** Generation is not proof: an emitted
file can still be rejected at typecheck, and families 1-3 failed exactly there.
One stem at a time:

```console
$ python3 tools/memslot.py --gb 8 --label tf -- python3 test_formal.py -j 1 <stem>
```

`test_formal.py` with NO stem at `-j 2` breaches an 8 GB `memslot` reservation
(peak observed 8.0 GB, killed); a single stem peaked at 3.2 GB. So this is one
proof at a time by necessity as well as by the task's own rule, and it is the
integrator's to run.

A stem that FAILS gets an `EXPECTED_FAILURES` entry naming its own failure, as
§4's original step 1 said. **A stem that PASSES is the better outcome and needs
no entry** — and it is worth saying out loud that eleven generating is not eleven
proved, so the honest reading of this table is "the generation half of the corpus
is in far better shape than 2026-10-03 recorded, and the proof half is
unmeasured here".

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 -c "import formal.arm64_proof_gen as G; G.audit_step_table('lib/ProofLib.lean')"
['entry 3 shadows entry 5', 'entry 4 shadows entry 47', 'entry 48 shadows entry 50']
$ python3 tools/memslot.py --gb 32 --label tf -- python3 test_formal.py -j 6
```
