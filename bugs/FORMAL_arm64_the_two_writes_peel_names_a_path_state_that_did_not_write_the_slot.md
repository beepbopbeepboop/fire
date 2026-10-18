# FORMAL_arm64_the_two_writes_peel_names_a_path_state_that_did_not_write_the_slot

**Area:** FORMAL, the arm64 proof generator's conditional-path peel.
`test_formal_call_proof_gen.py::TestANarrowTypedParameterGetsItsRange::
test_lean_accepts_the_three_examples` (`sgt8`), and the `maxRecDepth` half of
the oct-7 proofgen reds, which `f7bd05ea` closed by discharging a block's
first-step `runs_cons_seq` side condition with `first | (simp only [qT0, qS0]
<;> done) | rfl` instead of a bare `rfl`. **Status:
OPEN. Pre-existing — measured identical with and without this branch's fix.**

## What I ran

    $ python3 tools/memslot.py --gb 8 --label t -- \
          python3 test_formal_call_proof_gen.py TestANarrowTypedParameterGetsItsRange
    FAIL: test_lean_accepts_the_three_examples
    AssertionError: False is not true : sgt8 does not typecheck, and it did not
      before this fix either:
      sgt8_proof.lean:4306:10: error: Tactic `rewrite` failed: Did not find an
        occurrence of the pattern
      ⊢ arm64_matches_condition 13
      sgt8_proof.lean:4475:10: error: Tactic `rewrite` failed: Did not find an
        occurrence of the pattern
      ⊢ arm64_matches_condition 13

`sle8` and `ug8` in the same row are clean; only `sgt8` fails.

## What was seen

Both errors are on a `by_cases` arm's `hcond_2` proof, and both are the same
emitted line:

    rw [mem_read_two_writes_adj_uint _ (((s_0).sp - UInt64.ofNat 32) -
                                        UInt64.ofNat 16) _ _]        -- :4306
    rw [mem_read_two_writes_adj_uint _ (((s_1).sp - UInt64.ofNat 32) -
                                        UInt64.ofNat 16) _ _]        -- :4475

surrounded by facts about a DIFFERENT state:

    have hcond_2 : (arm64_matches_condition 13 s_2.nzcv = true) ↔ ¬(…) := by
      rw [hsid_2]
      simp only [arm64_reg_pc]
      simp only [sgt8_b2_qS0, …, sgt8_b2_qT6, hprior_0_n, arm64_reg, arm64_set_reg]
      rw [mem_read_two_writes_adj_uint _ (((s_0).sp - UInt64.ofNat 32) -
                                          UInt64.ofNat 16) _ _]

So the peel's address is computed from a path state (`s_0`, `s_1`) that does not
hold this store — the store is in `s_2`'s value flow — and the library's
`mem_read_two_writes_adj_uint` therefore has no occurrence to rewrite. Lean
quotes the goal's head (`⊢ arm64_matches_condition 13 …`) in the message because
that is the goal the rewrite is reported against, which is what makes the
diagnosis look like a missing `arm64_matches_condition` lemma rather than a
stale address.

**Why this is NOT the recursion-depth defect.**
That defect blamed the `lsl #12` immediate and `rfl`-over-a-composed-state; it
is real and is fixed (`9e0cbcec`, and then properly by `f7bd05ea`, which replaced
the bare `rfl` with the `first | simp <;> done | rfl` form), but it is a different
mechanism: the two errors here are `Tactic rewrite failed`, not `maximum
recursion depth has been reached`.
Measured by generating `formal/examples/sgt8.mojo` with the pre-fix generator
and running Lean on it — **the same two errors, at the same two lines**:

    $ git show 9e0cbcec~1:formal/arm64_proof_gen.py > formal/arm64_proof_gen.py
    $ … compile_formal('formal/examples/sgt8.mojo', arch='arm64', prove=True)
    $ lean .tmp/sgt8_proof_base.lean
    .tmp/sgt8_proof_base.lean:4306:10: error: Tactic `rewrite` failed: …
    .tmp/sgt8_proof_base.lean:4475:10: error: Tactic `rewrite` failed: …

## What I expected

That a peel whose slot is not in the addressed state's value flow would not be
emitted at all, or would be `try`-ed, rather than being emitted as a bare `rw`
that has to find an occurrence.

## The exact next step

Find the emitter that chooses the `(s_N)` in
`mem_read_two_writes_adj_uint _ (((s_N).sp - …) …) _ _` on a conditional path
(it is the `hcond_N` / conditional value-flow arm, not `_gen_run_cert`, since
the site is inside a `by_cases`), and make it select the path state that
actually performed the second write — or skip the peel when none did. A cheap
first probe: the same program with the `if` body emptied of the two stack
stores, which should remove both errors and confirm the peel is what fails
rather than the narrowing lemma around it.