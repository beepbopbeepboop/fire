# FORMAL_the_arm64_step_table_audit_read_a_branch_out_of_a_comment: twelve red
# examples nobody could see, because the suite raised before it generated one

**Area:** FORMAL / proof generation — `formal/arm64_proof_gen.py`'s
`audit_step_table`, and the census it was hiding.
**Status: the AUDIT is fixed (same commit); the twelve examples it was hiding are
re-measured ONE AT A TIME below and each of the four signatures now has the
obligation that fails, named from the generated file rather than from a truncated
tail. Nine of the ten are still red and still undiagnosed beyond that; one
(`wdiff`) is fixed on master and this doc's count was stale.**

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

## 5. Re-measured, one example at a time (2026-10-04, `work/formal19-5`)

Step 1 above is done, and it changed the census: **ten red, not twelve**, and
each of the four signatures is now named by the OBLIGATION that fails rather
than by the tail of a diagnostic. Every row is a measurement on this tree, and
the two Lean-side families were read out of the generated file with
`formal/lean.py::run_lean` on `output/<stem>_proof.lean` — because
`test_formal.py` shows only the last 300 characters of a failure, and that is
what made family 1 read as an ADRP page computation when it is not.

| # | examples | red? | first error in the generated file | the obligation it names |
|---|---|---|---|---|
| 1 | `count`, `fact`, `pow2`, `sqsum`, `sum` | 5 red, one shared first error | `sum_proof.lean:5903:16: error: Tactic 'rfl' failed` inside `have hx30fr_5 : (sum_b5_qS4 (({s_4 with pc := 4294968088}))).x30 = (st).x30` | the walk's "x30 survives from the initial state to the epilogue's reload" fact. Its goal is a `mem_read_u64` over a FIVE-deep `mem_write_u64` chain at `st.sp - 16`, `- 8`, `- 32`, …, and the fact's tactic is `simp +decide only [_VALUE_SIMP] ; all_goals rfl`. The separation rewrite IS in that simp set (`mem_read_after_write_u64_slot`), but its side conditions (`j < 2^64`, `k + j + 8 ≤ 2^64`, `j + 8 ≤ k`) are inequalities in the SYMBOLIC `st.sp`, so `decide` cannot discharge them, `simp` skips the rewrite, and `rfl` is left holding the chain. **B6's shape with the peel missing**, and the fix is already written down elsewhere: `formal/x86_64_endtoend_test.py`'s closing `hrip` peels the same shape with an explicit `key : ∀ m a v b, a + 8 ≤ b → …` and `repeat rw [key _ _ _ _ (by first | decide | omega)]` — "`repeat` in front of it peels every layer, and each layer's side condition is closed over literals" is that file's own sentence. The write offsets are already computed on this path (`ctx["stores"]`, from `_sp_stores`). Everything after line 5903 in these five files is cascade. **And the peel alone is NOT the fix — measured, see §5.1.** |
| 2 | `sgt8`, `sle8`, `ug8` | 3 red, one shared shape | `sgt8_proof.lean:4745:43: error: unsolved goals` on `FrameBound 131120 (let __src := Arm64State.init n 4294967968; {x0 := …, x29 := …}) n` | the universal theorem's FRAME-BOUND obligation, over the TYPED model's initial state — the 30-field literal this doc's author read as "the truncator shape". The next diagnostic is `The prover found a potentially spurious counterexample … abstracted … [3, t8s n, arm64_matches_condition 2 nzcv✝¹, arm64_reg 16 …]`: `bv_decide` gave up on the typed truncator terms inside that obligation. Nothing here is a codegen claim. It is the `t8s`/`t8u` half of `formal/types.py::lean_trunc_defs` meeting `FrameBound`, and the fix is to teach the bound's obligation those truncators. |
| 3 | `both`, `either` | 2 red, identically | `both_proof.lean:5517:8: error: (kernel) excessive memory consumption detected`, at `theorem both_compiles_correctly_universal`, 7.5 GB peak | **the "is it the library?" question above is answered: it is not.** One `formal/lean.py::ensure_library` later, with a freshly built `lib/*.olean`, both still fail, and they fail at the FINAL universal theorem of the file — every per-block certificate above it (`both_blk_0` … `both_blk_6`) is accepted. So this is the arm64 kernel-memory class (`BLOW.md` §0, `bugs/CODEGEN_bootstrap_resource_blowup.md`) at one declaration, and it is the only one of the twelve that costs more than 3 GB to observe. |
| 4 | `sum_range`, `wdiff` | **1 red, 1 already fixed** | `ValueError: unsupported cbz taken continuation to 0x100000330` (`sum_range` only) | `wdiff` GENERATES on this tree — its back edge is the unconditional `b` that `test_formal_call_proof_gen.py::TestLoopContractBlocks` pins, and that discovery works. Family 4 is one example now, and `bugs/FORMAL_sum_range_generation_refused_and_it_is_not_an_expected_failure.md` carries the diagnosis, which is BIGGER than this doc's "a missing `loop_test` or `cond_branches` entry": for `sum_range` the loop contract is never built at all, because the caller's loop-test rule asks for a `b` block whose target is a `cbz` block and this loop's back edge is the `cbz` block's own taken edge. |

**What this changes for the next session, and what it does not.** It closes none
of the ten: a named obligation is not a fix. What it does is make step 1 of §4
impossible to repeat — each family has a file, a line and a goal — and it
settles family 3's question, which was the one §4 said to look at first. Two of
the families are cheaper in the GENERATOR than the census showed: family 1 is one
missing peel in one emitted fact (five examples), and family 3 is one
declaration's memory (two examples) — though "cheap to emit" and "cheap to
measure" are different things here, and family 3 costs 7.5 GB per example.

**Not claimed:** that adding the peel to `hx30fr` would make those five PROVE.
The `rfl` failure is the FIRST error; the five examples' remaining obligations
have never been observed with it discharged, and nothing measured here says
anything about them.

## 5.1 Family 1's peel removes four of the five layers, and the fifth is not a
## frame question at all

Measured, because §5 says "the fix is known" and that sentence needs its
qualifier. The goal, read out with `trace_state` substituted for the failing
`all_goals rfl` (`output/sum_proof.lean` up to line 5903, `.tmp/goal.lean`):

```
⊢ mem_read_u64
      (mem_write_u64
        (mem_write_u64
          (mem_write_u64
            (mem_write_u64 (mem_write_u64 st.mem (st.sp - UInt64.ofNat 16).toNat st.x29)
                               (st.sp - UInt64.ofNat 8).toNat st.x30)
            (st.sp - UInt64.ofNat 32).toNat st.x19)
          (st.sp - UInt64.ofNat 24).toNat st.x20)
        (UInt64.ofNat 4294968008 - (UInt64.ofNat 4294968008 % 4096 - …)) …)
      (st.sp - UInt64.ofNat 8).toNat
    = st.x30
```

The read is at `sp - 8`; four of the five writes are at `sp - 16`, `- 8`, `- 32`,
`- 24`, all literal `sp - K`, all strictly below the read. `mem_read_after_write_u64_slot'`
is exactly that shape (its own docstring: "the write slot sits *below* the read
slot, `k + 8 ≤ j`"), and its side conditions — `j < 2^64`, `k < 2^64`,
`k + j + 8 ≤ 2^64`, `k + 8 ≤ j` — are LITERAL arithmetic once `j` and `k` are
named, so four applications of

```lean
rw [mem_read_after_write_u64_slot' _ _ (j := J) (k := 8) (by decide) (by decide) (by decide) (by decide) _]
```

go through and leave `mem_read_u64 (mem_write_u64 st.mem <addr> <v>) (st.sp - 8).toNat = st.x30`.

**The fifth write is at an ADDRESS, and it is the whole remaining problem.** It
is the `ADRP`-page materialisation of a module-global slot, and its address is
`UInt64.ofNat 4294968008 - (UInt64.ofNat 4294968008 % 4096 - …) * 4096 +
UInt64.ofNat 8` — a computed expression, not `sp - K`. Separating it from the
read needs `<addr> + 8 ≤ (st.sp - 8).toNat` or its negation, which is a fact
about where `sp` is RELATIVE TO THE GLOBAL — not a frame question at all (the
frame lemmas are about `sp` against `sp`), and not one anything in scope states.
`hbnd : FrameBound 131168 st arg` is about the frame, and the read is at `sp - 8`,
so `FrameBound` does not reach it either.

So family 1 is two obligations, not one: a mechanical four-layer peel, and one
disjointness fact between a global's address and the stack. The second is a new
kind of argument for this walk — the only global-address write it has met so far
is in the frame-slot prologue pair, which the peel handles because both sides are
`sp - K`.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 -c "import formal.arm64_proof_gen as G; G.audit_step_table('lib/ProofLib.lean')"
['entry 3 shadows entry 5', 'entry 4 shadows entry 47', 'entry 48 shadows entry 50']
$ python3 tools/memslot.py --gb 8 --label tf -- python3 test_formal.py -j 1 sum
  [1/1] FAIL  sum  (build/proof failed: t64.ofNat 4294968008 - …)
$ python3 tools/memslot.py --gb 8 --label le -- python3 .tmp/leerr.py output/sum_proof.lean
/…/output/sum_proof.lean:5903:16: error: Tactic `rfl` failed: The left-hand side
  mem_read_u64 (mem_write_u64 (mem_write_u64 (mem_write_u64 (mem_write_u64 …
$ python3 tools/memslot.py --gb 8 --label tf -- python3 test_formal.py -j 1 both
  [1/1] FAIL  both  (build/proof failed: build: proof check failed:
  both_proof.lean:5517:8: error: (kernel) excessive memory consumption detected)
```
