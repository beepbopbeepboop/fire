# FORMAL: `test_formal_eval_eq_mojo_bridge.py` is red on head (5 failures)

`test_formal_eval_eq_mojo_bridge.py` is not registered in `tools/suite.py`, so
this is not a gate red — it is a standalone test file whose last recorded state
is unknown. Measured 2026-11-18 in `work-7647`, with `lib/ProofLib.olean`
built:

    python3 tools/memslot.py --gb 8 --label bridge -- python3 test_formal_eval_eq_mojo_bridge.py

Result: `Ran 32 tests in 539.8s`, `FAILED (failures=5)`, peak 6.1 GB, exit 1.
The failures were confirmed not to be caused by the work that touched
`formal/arm64_proof_gen.py` in the same tree: three of them are assertions on
`lib/ProofLib.lean` or on generated text that the change does not emit, and the
two Lean ones are a program (`bigbody`) with no calls at all.

## Status 2026-11-19 (`work-7663`): four of the five are fixed; `bigbody`'s
## kernel-memory wall is the machine half, not the bridge

Read the sections below as the original report; this entry corrects item 2's
attribution and records what landed.

**Fixed, and each was a real defect rather than a stale expectation:**

* item 1 (both `lib/ProofLib.lean` pins). The library gained the second call
  handler (`evalExpr callFunc callFunc2 …`) after the pins were written, so
  both regexes now include it: `evalExpr`'s `bnot` arm and `evalExpr_unop`'s
  `"bnot"` arm, and the signed-comparison count now matches
  `sKey (evalExpr callFunc callFunc2 l env) …`. The library's arms are right;
  the pins were reading a signature that no longer exists.
* item 3b (`TestTheNestedExprRoutes`' recursor fixture). Besides the `env`
  typing (`Nat` where the hypothesis applies it to a name), the fixture never
  declared `ev`/`evArgs` at all, so `E.rec` was being applied to unknown
  identifiers; and its list motive stated the fold at the accumulator `1`, which
  the `cons` case cannot use. The fixture is now self-contained (it reuses
  `MUTUAL_DEFS`), the environment is `String -> Nat` as `MojoEnv` is, and the
  list motive is `∀ acc, …`. `RECURSE_ROUTE` elaborates and the three routes
  typecheck.
* item 3a (`[n] = mojo n`). The emitted site now carries the arity-2 handler
  too, so the needle is `[n] ((fun name arg0 arg1 => 0)) = mojo n` — the
  argument list AND the handler, not a substring that would also match the old
  text.
* item 2's BRIDGE half. The two-phase emission (`by_cases` over half the
  conditions, `simp_all`, then the rest) is the failure: the mid-proof
  `simp_all` rewrites a goal whose `mojo`/`_go` are already unfolded but whose
  remaining `if` tests are still open, and the second pass exhausts simp's step
  budget (`simp` failed: maximum number of steps exceeded, 4 goals; measured on
  the isolated `bigbody` bridge with `lib/ProofLib.olean` built). One split and
  one `simp_all` closes the same bridge in one pass, so both generators emit
  that. A Lean-free pin (`test_a_many_condition_bridge_is_split_once`) fails on
  the two-phase text.

**Item 2's remaining half is NOT the universal bridge and NOT the call
bridge.** With the bridge replaced by `sorry`, the generated file still dies at
`(kernel) excessive memory consumption detected`, and the machine half alone
needs more than 7.9 GB at `-M` (the generated-proof budget is 6 144 MB). Three
real charges were found and removed on the way, all in
`formal/arm64_proof_gen.py`, with Lean-free pins in the same test:

* the universal emitter's decode lemmas ran to `len(code)` instead of
  `_exec_code_limit(code)`, emitting 43 lemmas for the interned trap messages
  (332 vs 289). Each is an `rfl` over the WHOLE code list;
* every `…_sr_{i}` re-derived its word with `native_decide` even though the
  file already declares `…_insn_{i}` by `rfl` (289 native compilations and
  289 full `List.getD` walks removed);
* `_step_facts`' closed `UInt32` discriminator and the "`BL` past the slice"
  word read were `native_decide`; they are `decide`/`rfl` now. The `BL` one is
  written once per CFG PATH, so `bigbody`'s 64 paths asked Lean's native
  compiler for the same closed decision 320 times. `native_decide` occurrences
  in the `bigbody` proof: 4 809 → 247.

That cuts the wall but does not close it: the machine proof enumerates all
2^6 paths of the six independent `if`s, and its 1 156 declarations still exceed
the 6 GB generated-proof ceiling on their own. The next step is the one the
earlier `FORMAL_eval_eq_mojo_is_undecidable_over_a_free_n` doc ended at -- a
compositional / contract-shaped machine proof instead of one certificate per
CFG path -- or a justified raise of a generated proof's `-M`, which is an
owner decision (`doc/POLICY_memory_over_4gb.md`). Until then `bigbody` cannot
be the fixture this file checks with `check_proof_cached`, and the named
command below does not exit 0.

## Status 2026-11-19 (second round): 35 tests run with Lean on; `bigbody` is the only failure

Measured on a worktree from master with `lib/ProofLib.olean` built
(`tools/suite.py prooflib`): `python3 test_formal_eval_eq_mojo_bridge.py`
runs 35 tests in ~1 500 s, one fails (`bigbody`). The earlier 27-test run in
8 s was a false pass: its Lean half skipped for want of the olean.

* `bigbody` standalone (`check_proof_cached` on its generated proof) was
  killed by `tools/memcap.py` at an 8 GB ceiling and again at 24 GB, before
  Lean finished. One `lean` process was at ~7 GB while running. So the
  machine half is not merely over the per-proof `-M 6144`; the tree is well
  past the policy's 24 GB `module` class. This is a RESOURCE result, not a
  verdict on the proof.
* Consequence: `bigbody` cannot be checked in a bucket at its current cost.
  The two remaining routes are the ones already recorded above: a
  compositional machine proof (not one certificate per CFG path), or an owner
  decision to raise the generated-proof budget (`doc/POLICY_memory_over_4gb.md`).
  Neither is a one-round change, so this round stops at the measurement.

## Status 2026-11-19 (third round, `work-7671`): the two removable machine-half
## charges are out and pinned; the wall now stands in the block-theorem prefix

Carries the second round's measurement (entry above). This round removed two
real wastes from the machine proof in `formal/arm64_proof_gen.py`, pinned each
without Lean, and re-measured the
standalone proof, one run per variant, under the same conditions (direct
`lean -j 4 -M 6144 -T 200000`, `lib/ProofLib.olean` built, `LEAN_PATH` as
`formal/lean.py::_run_lean` uses it).

**What landed** (arm64 universal lane only; the dylib and frame lanes keep the
flat list — `test_formal_call_proof_gen.py` pins `dylib_code_list`'s shape as
the whole image in one list, and neither lane was over budget):

* **The byte reader is per-block, not a flat walk.**  The image is now
  `…_code_blocks : List (List UInt8)` (38 blocks of 64 bytes, last one short)
  and `…_code` takes one `getD` per level.  The old reader was one
  `List.getD` walk of the whole 2 377-byte flat list per byte, and
  `arm64_step` reads the instruction word at every step of every CFG path —
  the kernel re-derives the read at every occurrence, so the flat walk is
  O(image) per read.  Per-read step model, measured on this image: ~3 500
  reduction steps (spine rebuild 2 377 + peel up to 2 377) down to ~2 400
  (spine rebuild 2 406 + peels ≤ 102 + div/mod); the image spine is rebuilt
  per read in BOTH spellings, so the win is the peel, not the spine — the
  block form is ~30% cheaper per read, not an order of magnitude.
* **The per-block advance applies its runs certificate once.**  The old order
  proved the advance's `∃ s, … = some s` with `refine ⟨(state), ?_⟩; exact
  cert` and THEN re-emitted `hcert := cert`: the block's runs theorem
  instantiated at a nested run-exit state — whose kernel check is the
  advance's whole cost — applied twice per advance, 1 788 times across
  `bigbody`'s 894 advances.  The top-level site in the same function already
  emitted `hcert` first and inhabited the existential by it; the per-block
  site predated it.  It now applies the certificates 894 times.

**Lean-free pins** (in `test_formal_eval_eq_mojo_bridge.py`,
`TestBridgeSimpset`; each verified to FAIL on the pre-fix emission and PASS on
the post-fix): `test_the_code_image_is_read_per_block_not_walked_flat`,
`test_the_block_advance_applies_its_runs_certificate_once`, and the re-derived
`test_the_decode_lemmas_stop_at_the_executable_region`, which now reads the
image bytes back from `bigbody_code_blocks` (byte-identical to the old flat
list, 2 373 code bytes + the 4-byte RET sentinel).

**Measured, this round's window, standalone `bigbody` proof** (the kernel's
`-M 6144` throws per declaration and the process runs on to `maxErrors`; the
uncapped peak RSS reflects how far the error cascade goes, not the fix —
compare first-error line and user seconds):

| variant | first kernel error | errors | user s |
|---|---|---|---|
| pre-fix emission | `bigbody_b40_self1`, L16919 | 101 (maxErrors) | 3 742 |
| C3 only | `bigbody_b40_self1`, L16919 | 101 (maxErrors) | 3 723 |
| C1 + C3 (this commit) | `bigbody_b40_self1`, L16957 | 100 (maxErrors) | 3 548 |

(The L16957 vs L16919 offset is the 38-line block image itself; the
declaration is the same. The C3-only and pre-fix runs shared the machine,
the C1+C3 run did not, so the user-second differences — 3 742 → 3 723 →
3 548 — are indicative, not a clean A/B.)

Two conclusions:

* **The wall has moved into the block-theorem prefix.**  In the first round's
  window the prefix (through the whole block-theorem section, the universal
  theorem as `sorry`) checked at 5.5 GB and the breach was in the universal
  half (the first round's entry: the machine half alone needs more than
  7.9 GB at the 6 144 MB ceiling).  In this window ALL variants — including
  the unmodified pre-fix emission — first hit the kernel ceiling at
  `bigbody_b40_self1`, the first self-theorem of the LAST block, before the
  universal theorem is read at all.  The first round's 5.5 GB is 12% under
  the ceiling, so a shared-machine window can exceed it either way (the
  second round says the same of its 8/24 GB kills).  No variant regressed:
  C1 + C3 dies at the same declaration as the pre-fix emission, and C3-only
  is byte-identical to the pre-fix emission through the prefix.
* **The shape problem is unchanged.**  The universal half is one certificate
  per CFG path (64 paths, 894 advances, 384 leaf closures), superlinear in
  path depth (first round's window: a 4-path program checks at 4.0 GB; an
  8-path program dies at the ceiling).  C3 halves the certificate
  applications and C1 cheapens every byte read; neither changes the shape.

**Not done, in order** (the next round's work, each a real change rather than
a re-measure):

1. **The block-theorem prefix back under the budget.**  The hot declaration
   class is the per-block `…_self{k}` theorems: each rewrites
   `runs_cons_seq` over the block's nested `qS`/`qT` record-update chain
   (each `qS_k` embeds `qS_{k-1}`, so the state term grows with `k` and the
   section is quadratic in block length).  The first candidate is the
   round-1 recipe applied to this section: hoist the shared `qS_k`-chain
   simplifications into named per-block facts, the way the `…_sr_{i}` /
   `…_insn_{i}` hoist removed the per-step recomputation from the step
   lemmas.
2. **The compositional universal rewrite** in `_gen_universal_e2e_cfg`:
   replace the DFS that emits the whole walk per leaf with ONE inductive
   walk over the block sequence (a single chain of `rec1_glue_gen` advances
   and `go_exit_cbz_taken/fall` edges, with `hcond`/`hprior` closed once per
   (block, branch) instead of per leaf).  `lib/Contracts.lean`'s
   `Refine.BlockCert` / `runs_to_body` is the existing machinery, and the
   generated file already carries the pieces it composes: `bigbody_prog`,
   the 29 `bigbody_blk_N` block theorems, and the `…_runs`/`…_mid`
   certificates.
3. **Corpus verification** as the `formal_sweep` heavy job (the integrator's):
   every arm64 generated proof now carries the block-chunked image, and
   `test_formal_eval_eq_mojo_bridge.py`'s Lean half re-checks the four
   fixtures from scratch on the new emission.

The named command (`memslot --gb 8 -- python3 test_formal_eval_eq_mojo_bridge.py`,
run 2026-11-19 in this window) does not exit 0:

* The three light fixtures got fresh Lean checks on the post-fix emission and
  PASS with 0 sorries each — verdicts published in the CAS at 19:38:29
  (`ifonly`), 19:39:07 (`condassign`), 19:40:04 (`elif3`), keyed on exactly
  these generated bytes. No regression from C1/C3 in any fixture that fits
  the budget.
* `bigbody`'s fresh check started at 19:40:04 and published no verdict: the
  8 GB process-TREE ceiling killed the whole harness ~5-8 minutes into the
  check (memcap: BREACH 8.0 GB, 3 procs), before the 1500 s wall and before
  `maxErrors`. So in this window the block-theorem prefix is not merely
  "over the 6 144 MB per-declaration budget" — one `bigbody` check alone
  takes the process-tree total past 8 GB while it is still in the prefix
  (consistent with the standalone runs above throwing `(kernel) excessive
  memory consumption` at `bigbody_b40_self1`, L16919/L16957, before the
  universal theorem is read). `TestBridgeTypechecks` would report `bigbody`
  as the single red; the tree kill just arrives first.
* The eight Lean-free pins (including the three from this round) run green in
  this window (`Ran 8 tests ... OK`, 0.2 GB).

## The five, grouped by root cause

1. **`lib/ProofLib.lean` no longer has either spelling the test pins.**
   - `TestBitwiseNotIsNotLogicalNot.test_eval_expr_renders_bnot_as_a_complement`
     wants `| MojoExpr.unop "bnot" operand => evalExpr callFunc operand env ^^^ (0xFFFFFFFFFFFFFFFF : UInt64)`
     in `evalExpr`. The regex matches nothing.
   - `TestBridgeSimpset.test_skey_is_what_evalexpr_compares_with` reports
     `n_signed == 0`: `evalExpr` renders no comparison as `sKey l < sKey r`.
   The two are one question — which `MojoExpr` arm spellings the library has —
   so read `evalExpr` and re-derive BOTH pins from what it actually says now
   (or re-add the arms if they were lost rather than renamed).

2. **`bigbody`'s universal bridge exceeds Lean's simp step budget, then its
   kernel memory ceiling.**
   - `TestBridgeTypechecks.test_bridge_typechecks_with_no_sorries(program='bigbody')`:
     `bigbody_proof.lean:28:104: error: simp failed: maximum number of steps
     exceeded`, then a cascade of
     `(kernel) excessive memory consumption detected` from line 1899 onward.
   `bigbody` has 8 independent `if (n & 2**k)` conditions and no calls, so this
   is the attr/condition-multiplication cost in the universal `eval_eq_mojo`
   the class is about, not the call bridge. Likely the same class as the
   bitops/pc-fact kernel-memory fix (unfolding more than the goal reads); the
   next step is to measure whether `_eval_eq_conds_tactic` splits into more
   `by_cases` than the proof's `simp_all +decide` set can carry.

3. **Two text expectations of the current emission changed.**
   - `TestTheBridgeBindsEveryParameter.test_the_generated_ast_carries_a_name_list_and_the_sites_pass_one`
     wants `[n] = mojo n` in a one-parameter proof; the emitted theorem ends
     `... ((fun name arg0 arg1 => 0)) = mojo n`, so the literal needle no longer
     matches the current (correct) shape.
   - `TestTheNestedExprRoutes.test_the_COMBINED_recursor_takes_a_motive_for_the_LIST_too`
     feeds a `MojoExpr.rec` hypothesis with the wrong argument order:
     `Case.lean:7:31: Function expected at env ... this term has type Nat`.
     That is the TEST's own fixture typing the recursor wrongly, not the library.

## What to do (ordered)

1. Fix the `MojoExpr.rec` fixture first (item 3b): it is the only failure with a
   type error that names the mistake, and a wrong fixture hides the library
   question.
2. Re-derive the two `lib/ProofLib.lean` pins (item 1) from the library text.
3. Re-derive the `[n] = mojo n` needle (item 3a) from the emitted file; do not
   weaken it to a substring that would also pass for the old text.
4. Only then attack item 2, and do it as a measurement (one Lean run per
   variant, `-M 6144`): the question is whether the condition split or the
   emitter's simp set is the cost.

## Done when

    python3 tools/memslot.py --gb 8 --label bridge -- python3 test_formal_eval_eq_mojo_bridge.py

exits 0.
