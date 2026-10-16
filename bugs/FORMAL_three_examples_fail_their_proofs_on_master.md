# `count` and `pow2` fail their generated proofs on master, and both are now DECLARED

**Status 2026-10-08 (`work/formal255-docs`): re-measured on this tree — both
rows are now `KNOWN-GAP`, so the title's "neither is in `EXPECTED_FAILURES`" is
no longer true and is corrected above.** `python3 test_formal.py -j 1 count
pow2` reports `PASS=0 KNOWN-GAP=2 FAIL=0`, and the declared reason is the
return-frame read this doc is about. The diagnostics have MOVED: the current
failure is the recursion contract's BASE case replaying the STEP walk —
`count_proof.lean:5939` / `pow2_proof.lean:6232` report `Unknown identifier
ih` and the `frameBound_descend_le` application does not typecheck against
`hbnd : FrameBound 131152 st 0`, and each proof ends in "(kernel) excessive
memory consumption detected". The x30 materialised-address read this doc was
written about (`count_proof.lean:5909`) is still one of the sites. The fix is
in `formal/arm64_proof_gen.py`'s recursion-contract emit (the base bullet is
emitted with the step body); that file is claimed by a sibling formal worker,
so it is recorded here rather than changed. `test_formal.py`'s
`EXPECTED_FAILURES` and
`test_formal_call_proof_gen.py::TestTheReturnFrameReadsX30ThroughAMaterialisedAddress`
are the standing pins.

**RE-MEASURED 2026-10-08 (`work/formal206-docs`) on `master` at `3bc7d54b`, and
the failure has MOVED AND GROWN.** The x30 frame read this doc was written about
is still one of the diagnostics, but it is no longer the only one: the proofs
now stop at **nine diagnostics**, and three of them are a defect in a *different*
part of the generator that this doc never named — **the recursion contract's
BASE CASE replays the STEP walk.** The inventory, from
`python3 tools/memslot.py --gb 8 --label cnt -- python3 fire.py build --formal
--backend=arm64 -o .tmp/count.aout formal/examples/count.mojo` (`pow2` fails at
the corresponding sites, `pow2_proof.lean:6232`/`:6738`):

```
count_proof.lean:2767:74  native_decide: ¬909189220 >>> 5 &&& 16383 &&& 8192 = 0 is false
count_proof.lean:2696:212 unsolved goals (hinsn : arm64_read_insn count_code 4294969200 = 909189220)
count_proof.lean:3600:58  maximum recursion depth has been reached
count_proof.lean:5904:185 decide proved a proposition false
count_proof.lean:5909:18  rfl failed                                   <- THIS doc's x30 frame read
count_proof.lean:5927:54  Unknown identifier `hk`                      <- new: inside hbase
count_proof.lean:5935:103 hbnd : FrameBound 131152 st 0, expected `arg`<- new: frameBound_descend_le
count_proof.lean:5939:19  Unknown identifier `ih`                      <- new: inside hbase
count_proof.lean:6435:8   (kernel) excessive memory consumption detected
```

### The new defect: `count_contract`'s `hbase` bullet emits the step body

The three new diagnostics are one defect and it is in the BASE case, not the
step case. The theorem is emitted as

```
5817: theorem count_contract (fuel : Nat) (arg : UInt64) (st : Arm64State) … := by
5823:   refine contract_sound count_prog mojo 83 83 131152 ?_ ?_ arg st fuel hfuel hpc hx0 hbnd hx30ret
5824:   · intro fuel st hb hpc hx0 hbnd hx30ret         <- hbase's binders (fuel, st, then 5 hyps)
      …   (the hbase body spans 5824-6177)
5926:       have hbndsub_2 : FrameBound 131152 (… (arg - 1) := by
5927:         have hargne0 : arg ≠ 0 := by intro h; rw [h] at hk; simp at hk   <- `hk`,`arg` are STEP-only
5935:         have h := frameBound_descend_le 131152 32 (st) arg (arg - 1) … hargrel hPge hbnd
5939:     have hsub_2 := ih (…) ((fuel - 83)) …              <- `ih` is STEP-only
6178:   · intro k arg st fuel hk hb hpc hx0 hbnd hx30ret ih  <- hstep's binders
```

`hbase`'s signature (from `lib/Refine.lean::contract_sound`) is
`∀ fuel st, BASE ≤ fuel → st.pc = entry → st.x0 = 0 → FrameBound stride st 0 →
rets → Post … 0` — it has **no `arg`, no `hk`, no `ih` and no induction
hypothesis at all** — which is exactly what Lean reports at 5935 (`hbnd has type
FrameBound 131152 st 0`) and at 5927/5939. The base case is proving `arg = 0`
and cannot recurse, yet the walk reached the program's `count(n-1)` call and
emitted the recursion-descent body (the `frameBound_descend_le` application and
the `hsub_n := {_ih} …` call) into it.

Read off this tree, the generator does this at
`formal/arm64_proof_gen.py:9193-9196`, which emits the `hbase` bullet with
`_cbase = {"cbz_force": "fall"}` and `emit_runs(…, "0", …)`: only the source
cbz's FALL edge is walked (`emit_runs` skips the taken edge when
`cbz_force != "taken"`, :8518), and the recursion-descent emission at
:8870-8911 (`frameBound_descend_le`, the `hargne0`/`hargrel`/`hPge` block,
`have hsub_{n} := {_ih} …`) is guarded only by "this call is a self-call", not by
"this walk is the step case". So **the base case is following the branch that
leads to the recursion call.** Two candidate mechanisms, and the owner's
measurement should pick one: (a) the `_cbase`/`_cstep` sense (:9195/:9200) is
hardcoded and is inverted for `count`'s encoding — it belongs decided from the
encoding, the way `_cbz_reg_const` (:8378-8381) already does for an internal cbz;
or (b) the walk is choosing the wrong source conditional, since `count` now
carries more prologue branches than it did when this contract was written (the
stack-floor guard, `bfeec991`, puts a conditional in every entry —
`FORMAL_the_stack_guards_getrlimit_is_counted_as_a_program_call.md`).

**The exact next step, and why it is not taken here:** dump the block table with
the walk's own `ARMPROOF_DEBUG=1` (:8544) and read which block `cbz_force="fall"`
lands in; if it reaches the `bl count`, the sense is inverted and belongs read
off the encoding. The recursion-descent emission should also refuse under
`_cbase`, because a base case that recurses is unprovable by construction, not a
tactic failure. `formal/arm64_proof_gen.py` is the write set of a LIVE claim —
`formal207-docs` (`FORMAL_dylib_export_loops_and_frame_bounds`, the
recursion/loop contract) — so this is filed in the Status rather than fixed from
here, per the same rule
`bugs/DOCS_formal16_2_deleted_the_bit_test_doc_under_a_survey_another_worker_owns.md`
records.

**The 2026-10-04 status below is left in place and is still right about the x30
site; its "FIVE errors at TWO sites" is the measurement of that date and is
SUPERSEDED by the inventory above. Closing the x30 goal is necessary and no
longer sufficient: three of the nine diagnostics are this base-case defect, and
the two `native_decide`/decode ones point at a third.**

**Area:** FORMAL, arm64 — `formal/arm64_proof_gen.py`'s frame-address goals and
`lib/ProofLib.lean`'s address canonicalisation lemmas. **Status: the THREE reds
are now DECLARED and PINNED (2026-10-04, `work/formal25-6`) and the diagnosis
below is CORRECTED — the `(if False then …)` is not the cause. The two frame
cases are still red, and the fix is in a write set another worker holds. Found
2026-10-04 on `work/formal21-4` while landing the floor correction for `//` and
`%`, and it is PRE-EXISTING: it reproduces on the base commit.**

## Status 2026-10-08 (`work/formal170-docs`): the failure has MOVED — the frame-address `rfl` site is gone, and the true blocker is the emitter's base branch

**The `count_proof.lean:5330` `rfl` failure this file diagnoses below no longer
appears.** Re-measured on master
(`python3 tools/memslot.py --gb 8 --label t -- python3 test_formal.py -j 1 count
pow2`, 7.0 GB peak, both rows `KNOWN-GAP`, `PASS=0 KNOWN-GAP=2`), the generated
`count_proof.lean` now dies at three OTHER sites:

    count_proof.lean:5939:19: error(lean.unknownIdentifier): Unknown identifier `ih`
    count_proof.lean:6435:8: error: (kernel) excessive memory consumption detected
    have type FrameBound 131152 st arg in the application
      frameBound_descend_le 131152 32 st arg (arg - 1) ?m.1144 ?m.1145 hargrel hPge hbnd

The 5939 site is the "second error site" this file already waved at as *not
this doc's*. It is not a proof gap: the emitted `count_contract` refines
`contract_sound … ?_ ?_`, opens the **base** branch at
`count_proof.lean:5824` (`· intro fuel st hb …`, whose binder list has no `ih`,
per `lib/Refine.lean:746`), and then emits `hsub_2 := ih ({…}) (fuel - 83) …` at
5939 with `ih` unbound (the only `ih`-introducing branch opens 250 lines later,
at 6178). That is an emitter defect in `formal/arm64_proof_gen.py`, not a missing
`ProofLib` lemma. The 6435 kernel OOM is new here.

count and pow2 stay declared (`EXPECTED_FAILURES`) and pinned, so the *bug this
file was filed for* — an undeclared red — is still closed. What changed is the
root cause: the frame-address canonicalisation this file's body is about is no
longer what stops these two. **The fix is in `formal/arm64_proof_gen.py`, which
live formal workers hold (`formal178-docs`'s arm64 proof-gap rows,
`formal166-docs`'s arm64 proof-time row), so it is reported and not edited
here.**

## Status 2026-10-04 (`work/formal25-6`): declared, pinned, and the cause is not the dead `if`

**The failure is unchanged and reproduces byte for byte** (`python3
test_formal.py -j 1 count pow2`, 4.5 GB peak, `PASS=0 KNOWN-GAP=0 FAIL=2`; both
rows' text is the same goal).

**Item 3 of the next step below is DONE.** `count` and `pow2` are in
`test_formal.py`'s `EXPECTED_FAILURES` with the measured reason each, and
`test_formal_call_proof_gen.py::TestTheReturnFrameReadsX30ThroughAMaterialisedAddress`
pins them in both directions, Lean-free (3 cases, 0.16 s): the markers exist and
name a `sp - K` slot written through a materialised address, the generated
proof still carries the epilogue's `hx30fr_` read and the adrp-materialised
register write, and both programs still build on BOTH backends with proof
generation off — which is what says the gap is in the proof layer and not in
codegen. `wide_recv` was already marked (see
`FORMAL_wide_recv_model_has_no_domain_for_a_struct.md`), so all three of this
doc's examples are declared now and none is an undeclared red.

**Item 1 is DONE as a bisection and its reading was WRONG.** Run directly
(`python3 fire.py build --formal --backend=arm64 -o .tmp/count.aout
formal/examples/count.mojo`, ~2 min through `formal/lean.py::run_lean`'s bounds)
rather than through the suite's 300-character tail, `count` fails with FIVE
errors at TWO sites, and the informative one is `output/count_proof.lean:5330`:

    count_proof.lean:5330:16: error: Tactic `rfl` failed: The left-hand side
      mem_read_u64 (mem_write_u64 … (UInt64.ofNat 4294968008 -
        (UInt64.ofNat 4294968008 % 4096 - ((if False then UInt64.ofNat 1024 -
          UInt64.ofNat (2 ^ 21) else UInt64.ofNat 1024) * 4096 +
          UInt64.ofNat 8))).toNat (st.sp - UInt64.ofNat 1984))
        (st.sp - UInt64.ofNat 8).toNat
    is not definitionally equal to the right-hand side st.x30

That is `have hx30fr_5 : (count_b5_qS4 …).x30 = st.x30` — the EPILOGUE's restore of
`x30` — and the address is the whole of it. The slot was written through a
pointer the epilogue materialised with `adrp`/`add`: the
`arm64_set_reg 17 s (pc - pc % 4096 + 1024 * 4096)` successor at
`output/count_proof.lean:3440` is that materialisation, and it is a LITERAL, not
`sp - K`. So the `mem_read_after_write_u64_slot` peel in the `simp only` set has
no `sp - K` to match, the peel leaves the chain alone, and `rfl` is left holding
the raw goal. The emitter chose that address BECAUSE it is `sp - 1984`;
nothing emitted says so, and that missing canonicalisation is the obligation.

**The `(if False then UInt64.ofNat 1024 - UInt64.ofNat (2 ^ 21) else …)` is a
DEAD ARM and not the cause.** It is the `adrp` page-offset guard with its
condition already decided — `1024 ≥ 2^20` is false, and the emitted text at
line 3440 reads `if 1024 ≥ 2^20 then …` — `simp` normalises it without trouble,
and the tactic that FAILS is `rfl`. It is inside the failing goal because it is
part of the address, which is why reading the goal suggested it as the culprit.
`1984` itself never appears in the generated file: it is what Lean's printer
shows after `simp` has rewritten the literal address back through
`u64_ofNat_sub` and the `FrameBound 131152 st 0` hypothesis, so a reader grepping
the file for the offset in the error message finds nothing and has to read the
epilogue's `mem_read_u64 … (… .sp + 8)` to see the slot.

**The second error site is a different defect and is not this doc's.**
`output/count_proof.lean:5364:22: error: Tactic `introN` failed: There are no
additional binders or `let` bindings in the goal to introduce` — four times.
The emission is `refine ⟨…⟩ <;> (simp +decide only […])` followed by
`all_goals intro j hj`, and the `simp +decide` chain closed the goal on this
example, so the `intro` has nothing to introduce. That is a generator
robustness question in `formal/arm64_proof_gen.py` (an `intro` after a chain
that may already have closed), and the file is the write set of at least two
other claims — `FORMAL_arm64_known_proof_gaps.md` (the `arm64-cfg-leaf`
admissions 200 lines above) and the frame-address pair below. **Not attempted
here.**

**What is left, and who holds it.** The missing lemma is a canonicalisation from
a materialised (`adrp`/`add`) address back to the frame slot it was chosen to
be, which is the same family as
`bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md` (claimed `formal25-2`) and
`bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` (claimed `formal25-3`).
Until one of them teaches the generator to say `sp - K` for a materialised
address, these two examples stay red, and now say so.

## What was run

```console
$ python3 tools/memslot.py --gb 8 --label base-ex -- python3 test_formal.py -j 1 count pow2 wide_recv
  [1/3] FAIL  count  (build/proof failed: t64.ofNat 4294968008 -
            (UInt64.ofNat 4294968008 % 4096 -
              ((if False then UInt64.ofNat 1024 - UInt64.ofNat (2 ^ 21) else UInt64.ofNat 1024) * 4096 +
                UInt64.ofNat 8))).toNat
        (st.sp - UInt64.ofNat 1984))
      (st.sp - UInt64.ofNat 8).toNat =
    st.x30)
  [2/3] FAIL  pow2   (same text)
  [3/3] FAIL  wide_recv  (build/proof failed: ImplementedError(...))
Results for arm64 formal proofs: PASS=0 KNOWN-GAP=0 FAIL=3
```

**Run against `da80b19a` in a separate worktree, which is where this tree's
branch was cut** — so this is not a regression from the floor correction, and the
three failure texts are byte-identical with and without it. The floor correction's
own two examples (`udivmod`, `floordiv`) pass on both architectures with **0
admitted `sorry`**, which is the comparison that establishes it.

## Why it matters more than three red rows

`test_formal.py`'s `EXPECTED_FAILURES` has four entries (`fib`, `countdown`,
`wge`, `subscript_var`) and the file's own stale check reports an entry that
STARTS PASSING as a failure. `count`, `pow2` and `wide_recv` are in **neither**
list: they are undeclared reds in a file the gate does not run (the eight
Lean-checking formal tests are `disabled=`), which is the shape the deleted
`TEST_registered_tests_in_no_bucket_never_run` doc was about (closed in
f87c0e31) with a different cause — nothing is expected, nothing is reported, and three of the corpus's
heaviest examples have no proving case.

`formal/lean.py`'s own measurement table names two of them as the *slowest
successful* proofs it knows (`count` 79.7 s / 2.71 GB, `wide_recv` 93.4 s /
3.00 GB — the largest generated file), so whoever last measured them had them
green. Something since then turned them red and nothing noticed, which is the
`FILES BLOCKED IS AN UPPER BOUND` property applied to a test file: a change
elsewhere moved them.

## The two shapes, and they are different bugs

1. **`count`/`pow2`: a frame-slot ADDRESS goal.** The goal is a statement that
   `(A - (A % 4096 - off)).toNat = (st.sp - 1984)` for a literal `A =
   4294968008` — the `A % 4096` is the frame-slot canonicalisation
   (`lib/ProofLib.lean`'s `u64_slot_*` / `mem_read_*_slot` family, the same
   machinery `bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md` and
   `FORMAL_dylib_export_loops_and_frame_bounds.md` §1 are about). The `(if False
   then … else …)` in the middle is a **degenerate frame-bound constant** — the
   condition is literally `False`, so the branch is dead weight in the term the
   `simp only` has to normalise. `count` and `pow2` are `for`-loop examples, so
   the bound is the loop's, and a bound whose condition has simplified to `False`
   is the shape to look at first: it suggests the `FrameBound` hypothesis was
   specialised to a value that made one arm vacuous and the peel then has nothing
   to match.
2. **`wide_recv`: a struct field read with no model value.** The generator raises
   `NotImplementedError: model: a struct field read has no value in the semantic
   model (a `UInt64 → UInt64` function over the source's arithmetic); refusing
   rather than modelling it as 0`. That is `_expr_go` reaching a
   `self.<field>` inside an expression, and the refusal is RIGHT about the model
   (a field's value is not derivable from the source's arithmetic) — so
   `wide_recv` has no proof because its model has no answer, not because a tactic
   gave up. It is the by-reference receiver case: `formal/model.py`'s
   `wide_receiver_by_reference` is what makes the receiver a frame ADDRESS, and
   the field reads behind it are exactly what the model's `UInt64 → UInt64`
   shape cannot express.

## The next step

1. **Bisect `count`.** It is the smaller of the two frame cases and its goal
   names every constant, so `grep`ing the generated
   `output/count_proof.lean` for `4294968008` and reading the surrounding
   `have hframe := FrameBound …` is one step. The degenerate
   `(if False then … else …)` is the thing to explain.
2. **`wide_recv` is a model question, not a proof question**, and the honest
   options are the ones `bugs/FORMAL_wide_receiver_by_reference.md` and
   `FORMAL_a_one_field_struct_whose_only_field_is_a_nested_frame.md` already name:
   either a by-reference receiver's field read gets a model, or the example is
   stated over the one shape the model can express. It is a wide receiver with
   more than one field, so the second option is the one to measure first.
3. **In the meantime, `test_formal.py`'s `EXPECTED_FAILURES` should say so** —
   with a reason per row, which is what that table is for and what its stale
   check is built on. A declared red that nobody has fixed is a census; an
   undeclared one is a hole that reads as coverage.