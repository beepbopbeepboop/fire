# `test_formal_call_proof_gen.py`'s remaining reds after merging the oct-7 formal branches

**Area:** FORMAL / proof generation — `formal/arm64_proof_gen.py` and
`lib/ProofLib.lean`'s `arm64_step` arms. **Status: OPEN.** Filed by the
`work/merge-formal8-oct7` merger. The merge itself is complete; these are the
failures the narrow `test_formal_call_proof_gen.py` run still shows after every
*mechanical* merge artifact was fixed (undefined `_RLIMIT_STACK`, the
`_flush_push_depth` epilogue variant, a duplicated `for_target_tree`, a test
whose `setUpClass` never populated `cls.infos`, and so on — all fixed and
committed on that branch).

## Status, 2026-10-13 (`work/formal338-docs`): the `arm64_ext_imm12` attribution
## below is REFUTED; the recursion is `_code`'s `List.getD`, and it is deep, not
## infinite

Everything below is from 2026-10-08 and its "most likely cause" is wrong.  The
reproduction still holds — `mod_by_var`'s proof still stops with `maximum
recursion depth` — but the term that recurses is not `arm64_ext_imm12`:

* **`arm64_ext_imm12` reduces cheaply, at the DEFAULT depth.**  With the library
  built, `example : arm64_ext_imm12 (2436924415 : UInt32) = 131072 := by rfl`
  — and again with `decide`, `native_decide`, and `simp [arm64_ext_imm12]` —
  each checks at `maxRecDepth 1000` (not 100000).  So neither the ADD/SUB/CMP
  arm change nor an `@[simp]` lemma for it can be the cause, and the doc's
  option 2 cannot help a failing `rw` (which does not `simp`).
* **`set_option diagnostics true` names the recursion instead**:
  `List.get?Internal` / `List.rec` / `Nat.rec`, unfolding to depth > 100000.
  That is `_code`'s own definition,
  `formal/arm64_proof_gen.py::_gen_code_defs`:
  `def <name>_code addr := if addr < base then 0 else
  <name>_code_list.getD (addr - base) 0` — a `List.getD` indexed by a
  NEGATIVE-shifted `Nat`, so `List.get?Internal`/`Nat.rec` unfold on the index
  wherever the address is symbolic.
* **The depth boundary, measured on this tree** (the same
  `mod_by_var` proof, only `set_option maxRecDepth` moved):
  FAILS at `100000` (the generated file's own setting); TYPECHECKS at `150000`
  (69.8 s, 4.1 GB peak), `200000` (58.1 s), `300000` (58.9 s), `4000000`
  (48.0 s).  So it is deep-but-finite, needs ~1.2-1.5x the current bound, and
  costs ~60 s / ~4 GB once allowed to finish at all.
* **The `hprior` fact-count red is a separate question and is also not this
  cause.**  Its sibling `test_every_fact_is_proved_once_per_scope_and_in_scope`
  PASSES, so no fact is proved twice in a scope and the total (measured 3 / 9 /
  21 / 45 for 1..4 conditions = `3 * (2^k - 1)`) is minimal for the emission
  scheme.  The `2.2` ratio bound fails only at the 2 -> 3 step (21 / 9 = 2.33),
  because the counts are now small enough that the `-3` constant dominates; the
  ratio is 2.14 at the 3 -> 4 step.  Nothing here moved it.

**The corrected next step is a representation change in `_gen_code_defs`, not a
model or lemma change.**  A `List.getD` forces the `get?Internal`/`Nat.rec`
unfold; a `match addr with | <base + i> => byte | _ => 0` over the concrete
addresses (or a `ByteArray`/`Vector` read) is STUCK on a symbolic `addr`
instead of unfolding, which is what removes the depth.  It touches every
generated proof's `_code`, so it wants its own pass and a
`tools/formal_proof_census.py` re-measure, not a drive-by.

The pin is unchanged:
`test_formal_call_proof_gen.py::TestExternCallTheRunDoesNotReach.test_the_corpus_example_that_was_false_is_proved`
— it SKIPS without a built `lib/ProofLib.olean`, so build the library first
(`formal/lean.py::ensure_library`) before re-running it.

## What was run

    python3 tools/memslot.py --gb 8 --label t -- \
        python3 test_formal_call_proof_gen.py

    FAILED (failures=10)

and, class by class, the ones this doc is about:

    python3 tools/memslot.py --gb 8 --label t -- \
        python3 test_formal_call_proof_gen.py TestExternCallTheRunDoesNotReach
    # 1 failure: test_the_corpus_example_that_was_false_is_proved

## What was seen

* `TestExternCallTheRunDoesNotReach.test_the_corpus_example_that_was_false_is_proved`
  — `formal/examples/mod_by_var.mojo`'s generated proof does not typecheck:

      mod_proof.lean:4899:68: error: maximum recursion depth has been reached

  The site is the application of the generated step lemma
  `mod_by_var_sr_87` (an `ADD sp, sp, #32, lsl #12`, whose RHS is
  `s.sp + UInt64.ofNat 131072`) inside the run proof. `maxRecDepth` is already
  `100000` in the generated file, so this is a looping/deep kernel reduction and
  not a low limit.
* `TestSameImageCallLean.test_the_followed_call_proves_with_no_admission` — the
  same `maximum recursion depth has been reached`, in
  `same_image_leaf_proof.lean`.
* `TestNestedConditionFactSharing.test_the_fact_count_grows_with_the_paths_and_not_with_the_branches`
  — 2 -> 3 conditions grew the `hprior_` facts by x2.33 (9 -> 21) where the test
  bounds it at x2.2 ("the per-path memo makes this x2").
* `TestANarrowTypedParameterGetsItsRange.test_lean_accepts_the_three_examples`
  (`sgt8`) — a `rewrite` that no longer finds its pattern; the test's own
  message says `sgt8` "did not typecheck before this fix either", so this one is
  plausibly pre-existing.
* `TestTheZeroDivisorGuardAgainstLean` (4 rows) — the class's fixture generates
  no `q_compiles_correctly_universal`, which
  `bugs/FORMAL_the_div0_guard_measurement_class_traces_nothing_any_more.md`
  already records as the class's state on the base tree; treat those four as
  pre-existing.

## The most likely cause, and the next step

The three new ones all appear after `lib/ProofLib.lean`'s ADD/SUB/CMP immediate
arms changed to read `arm64_ext_imm12` (the `sh`-field fix merged from
`work/formal108/125/131/149`). That change is correct — it is what makes
`ADD sp, sp, #32, lsl #12` compute `+131072` instead of `+32` — and it is why
the generated `mod_by_var_sr_87` states `+131072`. What it also does is put a
non-reducible `arm64_ext_imm12 w` term in `work_step_add_imm64`'s statement
(`lib/ProofLib.lean:5117`), so unifying the concrete generated step with that
lemma now reduces through `arm64_ext_imm12`; the elaborator loops instead of
closing, and the same extra term is what makes the `hprior` fact set grow.

**Next step:** state `work_step_add_imm64` (and its SUB/CMP siblings) in the
generated proof's OWN terms — the concrete `UInt64.ofNat <shifted imm>` the
generator already computes in `_step_rhs` — rather than through
`arm64_ext_imm12`, or add an `@[simp]` lemma
`arm64_ext_imm12 (w) = ((w >>> 10) &&& 0xfff).toNat <<< (12 * ((w >>> 22) &&& 1).toNat)`
that the unifier can rewrite with without unfolding. Do NOT revert the model
change: the shift is a real correctness fix and its own tests (Peephole's
`sh = 0` side conditions, `test_formal_call_proof_gen.py`'s trap rows) depend
on it.
