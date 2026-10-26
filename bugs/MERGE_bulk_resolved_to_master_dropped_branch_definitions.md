# MERGE: the bulk `merge-qwen4-r2` merges resolved every conflict to master, which dropped the branch half of some signatures and definitions

**Status: DONE (2026-10-19).** The merge-damage cleanup this doc was the queue
for is finished. Every branch on the task list is merged, `suite-self-test`'s
dangling-citation census is green, `s | t` on two sets works, and
`SET_ALGEBRA_OPS` has one definition. What remains of the two bunny tasks that
worked this queue (`bunny-reds`, `bunny-merge26-r2-r2`) is FORMAL work, out of
`check`, and is tracked by its own bug docs rather than here (see "What is left").
This doc now stands as the record of how the damage went, the two shapes it
named, and the detector for them.

## What the round of 2026-10-16 closed

* `test_formal_value_model.py` **141 pass / 0 fail** (was 138/3), and
  `test_formal_peephole.py` **60/60** (was 56/60). Both mechanisms are described
  under "Known-open interaction failures" below, with the commit that landed
  each.
* `formal/model.py::container_operator_refusal`'s message interpolated `shown`,
  which the function's signature does not have — every program that reached it
  got a `NameError` traceback out of the compiler instead of a diagnostic, on
  both backends. Fixed by 78c928aa, pinned by a third BUILT sample in
  `test_refusal_taxonomy.py` (the two comprehension-element samples in that
  file's `SAMPLES` are HAND-COPIED, which is why nothing had noticed).
* Two dangling-citation names whose bugs are FIXED and whose docs were deleted
  with the fix, whose citation rewrites a later bulk merge reverted. One is the
  arm64 `#imm12` shift arms dropping their `lsl #12` (fixed by `5361903f`; pinned
  by `test_formal_call_proof_gen.py::TestUnsignedOffsetAccess`), the other is
  `audit_step_table` reading a branch condition out of a comment above
  `arm64_step`'s TBZ arm (fixed — `formal/arm64_proof_gen.py` now calls the
  anchored reader `_decoder_branch_conds`). Between them they had eight citing
  sites; all are rewritten to name the fixing commit and the symptom, and the
  second got its PIN back (`test_a_comment_that_quotes_a_condition_is_not_a_`
  `branch`, which 53dab793 added and a merge reverted). Restored by 9fd6117d.
* The `formal-x86-parity` `expect=` marker cited a doc that 4ceb7603 deleted
  along with its fix, while a later bulk merge reverted the TEST half of that
  fix — so the row went red on both backends again (the printf kind rule refuses
  the integers whose bits happen to be a double's) and the marker came back
  citing nothing. The fix is restored by 5e45d0b5.
* `AXIOM_CLOSURE`'s `work` row re-pinned to `(20, 0, 18, 0, 2, 0)` by c29680e8 —
  `f801d013`'s `work_u64_sign_zero_of_le` arrived kernel-checked, so `asked` and
  `clean` rose together and `reaches` did not.

**The pattern behind four of those five is the one this doc is about, and it is
worth naming: a merge that keeps the DOC half of a fix and reverts the CODE half
leaves the tree worse than either side.** A deleted doc with its citation
rewritten looks finished; the marker that cites it does not. A `Float64` row
reverted to the integers it replaced is red again with no doc to say so. Neither
is visible from `compile()`, which is why this doc's detection commands did not
find them and a gate job's anti-rot did.

## What is left, and what it is not

* **Five dangling citations — RESOLVED (2026-10-18).**
  `bunny-merge26-r2-r2` (55c0d477) rewrote the three that were on master's path
  and ratcheted the baseline down; `suite-self-test`'s dangling-citation census
  is green and `suite.py check` is 53/53 on this tree.
* **`ARM64Codegen._emit_set_union` — RESOLVED (2026-10-18).** The set-union
  emitter and the `SET_ALGEBRA_OPS` duplication it sat beside were both fixed by
  `bunny-merge26-r2-r2` (498f72fd), and the doc of its own was deleted with the
  fix. `SET_ALGEBRA_OPS` has one definition again.
* **What is genuinely left is FORMAL work, out of `check`, tracked by its own
  docs — not this one's queue:**
  * `test_formal_run.py` is **1328 pass / 4 fail** on this tree (was 1287/24 when
    this doc was written): the host-import wall (tag-generator), a comptime
    binding in another module, and two `wide-receiver-by-reference` rows — the
    last named in `bugs/FORMAL_wide_receiver_by_reference.md`. Not in the `check`
    bucket, so `suite.py check` does not report it.
  * `test_formal_call_proof_gen.py` has **6 failures**, all in
    `TestTheZeroDivisorGuardAgainstLean` (5) and `TestSameImageCallLean` (1) —
    Lean-gated, needing library/walk work rather than a test edit, tracked in
    `bugs/FORMAL_the_div0_guard_measurement_class_traces_nothing_any_more.md` and
    `bugs/FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_image.md`.

## What happened

The merge list has ~110 branches, almost all of them cut from an old master and
now largely superseded. The reconciliation used for most of them was mechanical:
**master's side wins every conflicting hunk, and the branch's non-conflicting
additions land**. That is right for a parallel *implementation* (the landed one
wins), and it is wrong for anything where the branch **extended** a shared
signature, import block, or function the master side also edited — there the
merge kept the branch's *body* and master's *signature*, so the name the body
uses is not bound.

The fixtures found so far, and the fixes already landed:

* `formal/arm64_proof_gen.py::_gen_extern_test` — `func_entry` twice in the
  signature and twice at the caller (a duplicate-argument SyntaxError, which
  `ast.parse` does **not** raise; only `compile()` does).
* `formal/model.py` — `ValueKinds.__init__` lost `bool_names`, `callee_is_bool`
  and `pointer_pointee_kind`; `bare_c_callee_is_project_function` and
  `fold_interpolated_literal` were absent; `bind_call_arguments` passed a stray
  fourth argument (`mappings`) to `_unspread_keyword_mappings`.
* `formal/monomorph.py` — `_template_call_shapes` and
  `_layout_independent_struct` absent (and `from contextvars import ContextVar`
  in `model.py`).
* `formal/x86_64_codegen.py` — `_for_target_refusal` absent.
* `formal/arm64_codegen.py` / `formal/x86_64_codegen.py` — the comprehension
  element-storage machinery was a mix of master's and the branch's; restored to
  master's `_emit_comprehension`/`_emit_compr_gen` and
  `_compr_append_elem`/`_compr_append_pair`.
* `tools/formal_isa_census.py` — `encode_call_r64` was in both `HARNESS_LIMITS`
  and `BACKLOG`.
* `tools/dangling_doc_refs.py` — `--ratchet` referenced an undefined
  `bare_regressions`.
* test files — missing test functions their `TESTS`/`ALL` lists named
  (`test_formal_monomorph.py` x4, `test_formal_contracts.py`,
  `test_formal_x86_64_dylib.py`), a `copy`/`copies` and an `om_got`/`omit_got`
  mixup, and a `must_refuse` leftover.

## How to find the rest

    python3 - <<'EOF'
    import subprocess
    bad=[]
    for f in subprocess.run(['git','ls-files','*.py'],capture_output=True,text=True).stdout.split():
        try: compile(open(f).read(), f, 'exec')
        except SyntaxError as e: bad.append((f, e.lineno, e.msg))
    print(bad)
    EOF

catches duplicate arguments and the like. Undefined *names* need a scope-aware
walk (AST or `symtable`); `git grep -n 'def NAME'` across the branch tips decides
whether a flagged name is a dropped definition (search `git log master..HEAD
-SNAME` for the commit that used it, then `git branch --contains` for the tip that
still defines it). Then run the touched suites:

    git diff --name-only master..HEAD | grep '^test_formal' 
    python3 tools/memslot.py --gb 8 --label t -- python3 <file>

## Known-open interaction failures — CLOSED 2026-10-16, and the decision

**Both mechanisms below are now ONE mechanism, and the reason it is master's is
recorded here because the next reader will otherwise re-open the question.**

`test_formal_peephole.py` was **60 pass / 4 fail**. Three of the four were one
bug and the fourth was a table row the merge dropped; landed as ebb9856d.
`work/formal53-docs` replaced `_repatch_branches(entries)` with
`_repatch_branches(entries, at, arch)` and master had its own `(entries, at,
arch)`. **The union is both, and neither:** the TARGET comes from
`Entry.branch`, which `_decode_region` records once at decode time in ORIGINAL
coordinates and never moves (the branch's insight, and the only thing that
survives a second deletion), and the TRANSLATION comes from `at`, master's
`_rebuild` table, which is also what a LABEL naming a deleted instruction lands
through — so a branch and a label cannot disagree about where a deleted byte
went. Master's version alone re-derived the original target by decoding the
branch WORD, which the previous call had already rewritten, so on the second
deletion a target was translated twice: measured, a branch below two deletions
came out one word short of its target, in an image that still runs. `BL` was
skipped outright (`_ARM64_BL_ROW` existed for exactly this and nothing read it)
and then raised `TypeError: 'int' & 'str'` once it did, because its fifth field
was the string `"call"` where every other row's is the `keep` mask.

`test_formal_value_model.py` was **134 pass / 3 fail**. The comprehension element
copy was the first two; landed as b0565b73. **Master's copy and master's
whitelist, widened, plus the branch's one real insight.** The branch shipped a
blacklist (`comprehension_element_borrowes_inner_container`) where master's is a
whitelist (`comprehension_element_is_flat_container`), and the union of the two
suites' tests picks the whitelist, for three reasons that are all measured:

1. `test_formal_run.py::COMPREHENSION_ELEMENT_CASES` is written against master's
   `comprehension_element_blob_refusal` and five of its ten rows are REFUSALS
   with that message's exact wording. The branch words its refusals from
   `comprehension_element_shared_inner_message`, so landing it would leave two
   suites disagreeing about the same program.
2. The branch's blacklist would ANSWER
   `{k: [v for v in [1, 2, 3]] for k in [1, 2]}`, which that table pins as
   refused (`a_dict_comprehension_whose_value_opens_a_container_is_refused`).
3. A blacklist fails toward "not noticed", which is the direction this tree keeps
   paying for.

What the branch had right is the SPAN: a container a CALL handed back is parked
above the blob region by `container_returned_blob_sites`, so one block is
rewritten per iteration while the ledger does not move at all, and a span read
off the ledger alone was zero. And a CONCAT of two flat containers reserves its
operands before its result, so the delta is 56 bytes where the result blob is 24
and the copy must be sized from the result. Both are in.

The third failure was a **refusal-WORDING mismatch** and was not about either
mechanism: `formal/model.py::container_operator_refusal` interpolated a name its
signature does not have, so `len(max(a, 0))` on `a = [1, 2]` died with a
`NameError` instead of being refused. Fixed by 78c928aa.

The rest of the touched `test_formal_*.py` files (about forty) have NOT been run
— running them all is the integrator's call, and any failure in one of them is a
candidate for this same class of dropped-definition or two-mechanism breakage.
The two mechanisms that most needed a decision were the comprehension element
copy and the peephole displacement repatch, and both are decided above.

## Two more shapes of this damage, and a cheaper detector

Both of these are invisible to `compile()` and to a scope-aware undefined-name
walk over the whole tree, because in both cases the name IS defined somewhere:

* **A doc half kept, a code half reverted.** 4ceb7603 fixed the parity row and
  deleted its bug doc; a later merge took the test file's old side and kept the
  deletion. The doc's disappearance is the signal that a fix happened, so a
  half-applied fix reads as a FINISHED one. The anti-rot half of the `expect=`
  mechanism is what caught it, not any static check.
* **A message that interpolates a name the signature does not have.**
  `container_operator_refusal(op, left_kind, right_kind, spelled_op, …)` and a
  body that says `{shown!r}` — and `shown` is defined NOWHERE in the file, so a
  tree-wide "is this name defined" walk reports it. What actually caught it was a
  *test row that asserted the message's first clause*, and only because a second
  row in a different file happened to reach the same arm.

So the detector worth having is not a name walk. It is: **for every
`expect=`/`disabled=` marker and every bug doc, ask whether the thing it names
still exists and still fails** — which is what `test_suite.py`'s two marker
checks do, and which found two of the five things this round closed. A doc whose
subject has been re-fixed is the shape nothing else sees.
