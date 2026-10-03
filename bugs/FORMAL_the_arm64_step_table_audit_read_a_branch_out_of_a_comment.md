# FORMAL_the_arm64_step_table_audit_read_a_branch_out_of_a_comment: twelve red
# examples nobody could see, because the suite raised before it generated one

**Area:** FORMAL / proof generation — `formal/arm64_proof_gen.py`'s
`audit_step_table`, and the census it was hiding.
**Status: the AUDIT is fixed (same commit); the twelve examples it was hiding are
NOT, and they are not fixed here.** Filed 2026-10-03 on `work/formal16-2`.

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

1. Re-measure the four signatures one at a time with
   `python3 test_formal.py <stem>` (each is 8.6 s – 297.8 s and 1.5–3.0 GB,
   `FORMAL.md` §12), and put each one in `EXPECTED_FAILURES` with the reason its
   own failure names — or fix it.
2. The two generator `ValueError`s (`sum_range`, `wdiff`) are the cheapest of the
   four: they are refusals, not failed proofs, so each is a missing `loop_test`
   or `cond_branches` entry rather than a Lean problem, and
   `bugs/FORMAL_arm64_known_proof_gaps.md` already names `wdiff` as "the same gap
   as `countdown`".
3. Family 3 (`both`, `either` failing on `ProofLib` itself) is the one to look at
   FIRST and it is not about generated proofs at all: the message names the
   library, so either a `.olean` is stale against `lib/*.lean` or the library
   stopped typechecking, and both are one `formal/lean.py::ensure_library` away
   from being distinguished.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 -c "import formal.arm64_proof_gen as G; G.audit_step_table('lib/ProofLib.lean')"
['entry 3 shadows entry 5', 'entry 4 shadows entry 47', 'entry 48 shadows entry 50']
$ python3 tools/memslot.py --gb 32 --label tf -- python3 test_formal.py -j 6
```
