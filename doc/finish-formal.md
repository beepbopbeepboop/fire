# finish-formal — the plan to close every open item in `bugs/FORMAL_*.md`

**Status: PLAN.** This document is the single plan an agent works from. Every
unit of work below has its own bug file under `bugs/plan/step-NN-*.md`; those
files are the work orders and this file is the design they consult. A step file
must not re-derive a design decision that is written here — if it disagrees with
this file, either the step is wrong or this file is, and one of the two is
edited before code lands.

**Audience.** An implementation agent (human or model) adding *support*, not a
reviewer. The deliverable of each step is a tree that builds, whose new
structure is wired end to end, and whose proof obligations are left as
`admit`/`sorry` placeholders rather than completed. See "Method" below.

**Sources.** The steps are decomposed from these `bugs/FORMAL_*.md` documents,
all read in full for this plan:

| doc | what it owns |
|---|---|
| `bugs/FORMAL_arm64_instruction_coverage.md` | the arm64 encoder/machine-model/lowering survey and its gap list |
| `bugs/FORMAL_peephole_rules_without_proofs.md` | the unproved arm64 and x86-64 peephole rules and the memory lemmas they need |
| `bugs/FORMAL_string_value_model.md` | what a string IS: representation, methods, the `String`-struct collision, the proof model |
| `bugs/FORMAL_set_value_model.md` | a set is a list: order, dedup, the missing set runtime |
| `bugs/FORMAL_known_limits.md` | the sweep residue: which refusals are true, and the ranked levers |
| `bugs/FORMAL_no_exceptions.md` | `raise` is termination: the EH-runtime gap and the host-module convention |

`FORMAL_model_package_split_left_duplicate_copies.md` is **deleted**: the
duplicate copies and fragments are gone from `formal/model/`, which is now the
one split module it was supposed to be (`__init__.py` plus the dependency
ordered `cfg`/`methods`/… modules).

**Not in scope.** The instruction that commissioned this plan says: if the work
amounts to *unifying the x86-64 port and the arm64 port*, skip it. The two
backends stay two code generators over one shared value model
(`formal/model/`). No step here merges the backends, and any step whose design
would collapse them into one emitter is out of scope; where a doc describes a
divergence between the two, the step closes it by making each backend agree on
the *answer* through shared tables, not by sharing instruction selection.

---

## Method — "structure, with `admit` and `sorry`, mostly"

The whole point of this plan is that the *shape* of every capability is added
and wired first, and the proofs are left as explicit holes. Concretely, for
every step:

1. **Add the structure.** Encoders (`formal/arm64.py`/`formal/x86_64.py`), the
   machine-model arm (`lib/ProofLib.lean` / `lib/X86.lean`), the proof-table row
   (`formal/arm64_proof_gen.py`'s `_STEP_CONDS` and its siblings), the lowering
   (`formal/arm64_codegen.py` / `formal/x86_64_codegen.py`), and the shared
   model table (`formal/model/`). Nothing in this list may be left half-wired:
   an encoder with no lowering is the "not an instruction" failure
   `FORMAL_arm64_instruction_coverage.md` is about, so the lowering and the
   model arm land together or not at all.
2. **State the obligation.** Every new Lean arm or rule gets its theorem
   *stated* with the correct hypotheses and the correct conclusion. The proof
   body is `by sorry` (term) or `by admit` (tactic). A `sorry` over a *false*
   statement is worse than no statement — `lib/ProofLib.lean`'s own header says
   so — so the statement must be the one the model actually satisfies; if it
   cannot be stated truthfully yet, the step file says which hypothesis is
   unknown and the theorem is not added.
3. **Record the hole — in ONE place, `lib/Scaffold.lean`.** Every scaffold
   `sorry` lives in `lib/Scaffold.lean` and nowhere else in `lib/` (see "Shared
   mechanics" S1). `lib/Peephole.lean`'s header promises "every theorem below is
   proved, and there is no `sorry`", `formal/peephole.py::declared_theorems()`
   treats *any declared name* as a licence, and `test_formal_admitted.py`'s
   `AXIOM_CLOSURE` pins how many declarations reach a hole. A scaffold written
   into those files breaks all three promises at once. The ledger
   (`formal/proof_gaps.py::SCAFFOLD_HOLES`) is compared against what
   `formal/lean.py::library_census` *measures* in `Scaffold` — an elaborated
   count, not a text scan.
4. **Keep the gates honest.** A suite that asserts "0 sorries" over a *generated*
   proof (the corpus rows in `test_formal_call_proof_gen.py`,
   `tools/formal_proof_census.py`'s baseline) gets its allowed-gap set widened
   in the same commit, with the step number in the reason string. Do not
   disable a gate to make a branch green.
5. **Prove later, in a separate commit.** A follow-up commit replaces `sorry`
   with the proof and removes the ledger entry. That commit is not part of this
   plan's definition of done for a step; the step's definition of done is
   "structure present, wired, truthful statement, hole counted, suite updated".

A step is **done** when: (a) the target construct builds and runs on *both*
backends (or the doc's stated scope), answering what CPython/`doc/ABI.md` says;
(b) the proof side has the new arm/table row/rule with a truthful statement and
a counted hole; (c) the named test(s) exist and pass; (d) the step doc's
"done-when" checklist is fully ticked.

---

## Global invariants (true for every step)

1. **One value model.** Anything that decides *what a value is* lives in
   `formal/model/` and is read by both backends; anything backend-specific is
   instruction selection only. `formal/model/__init__.py`'s own docstring is the
   authority for this split. A step that adds a table to one backend and not the
   other is wrong even if both currently answer the same.
2. **A refusal must be true of the file it is reported against.** This is
   `FORMAL_known_limits.md`'s load-bearing rule and it applies to new refusals
   introduced by a scaffold: a placeholder that refuses a construct with a
   message claiming a property the construct does not have is a bug, not a
   scaffold.
3. **No fabricated value.** If the model does not know a value, refuse; do not
   answer `0`. `FORMAL_string_value_model.md`'s proof-model section is the
   canonical failure (`printf("hi")` proved `false` because the model said a
   string literal was `(0 : UInt64)`).
4. **Architecture symmetry is a measured claim.** A shared table read by both
   backends is how symmetry is achieved; "both backends probably do the same"
   is not. Every step that touches semantics adds a differential row that runs
   the same source on both backends and against CPython where CPython applies.
5. **A doc is deleted when its bug is fixed.** When a step closes the last open
   item of a `FORMAL_*.md`, that doc moves to its fixed state (or is removed) in
   the same commit, and every citation of it is rewritten. `CLAUDE.md` and
   `tools/dangling_doc_refs.py` are the authority.
6. **`EXPECTED_FAILURES`/`KNOWN-GAP` must be moved deliberately.** A formerly
   passing example that a scaffolded hole makes red is either fixed or declared,
   never ignored; `step-28` fixed the `absval` frame-peel regression (commit
   `2e585ba4c`), and the general rule is that a formerly-passing example that
   now fails is a regression.

---

## Shared mechanics (verified against the tree, 2026-11-05)

The first draft of this plan assumed several things about the tree that are not
true. These are the corrected facts; every step file cites them by number.

**S1. Where a scaffold `sorry` lives.** `lib/*.lean` contains **no** real
`sorry` today (the `in_image_stub` / `Semantics` holes the first draft cited
were closed — `lib/ProofLib.lean` ~8434 says so; the word `sorry` appears only
in comments). The invariant is worth keeping, so scaffolds go in a new
**`lib/Scaffold.lean`**: it imports `ProofLib`, `X86`, `Peephole` (and
`Refine`/`Contracts` if a step needs them), is imported by **nothing**, and is
the last entry of `formal/lean.py::LIBRARY_MODULES`. A hole there cannot
propagate into any generated proof or any other library theorem. *Promotion*
(the follow-up proof commit) = prove the theorem, move it into its home module
(`Peephole.lean`, `ProofLib.lean`, …) and delete its ledger row.

**S2. The ledger and its census.** `formal/proof_gaps.py` holds
`SCAFFOLD_HOLES: dict[str, Hole]` keyed by declaration name
(`Hole(step, reason, kind)`). `test_formal_proof_gaps.py` asserts, from
`formal/lean.py::library_census`: (a) the set of declarations in `Scaffold`
that Lean reports as using `sorry` equals `SCAFFOLD_HOLES`' keys, both
directions; (b) every *other* library module reports 0 sorries. `library_census`
exists, is cached under `.libcensus`, and warns about the exact trap that bit
this tree before: **an up-to-date `.olean` makes `lean` print nothing**, so a
naive run reports 0 holes for a file with holes — use the census function, not a
hand-rolled `lean` call. (Never launch `lean` directly: `formal/lean.py::run_lean`
carries the memory and wall bounds.)

**S3. The licence check is name-only — keep it that way by construction.**
`formal/peephole.py::declared_theorems()` regexes `^theorem|lemma` names out of
`lib/Peephole.lean`, so a stated-but-`sorry` theorem there would *license* a
rule to fire. Therefore **rule theorems that still contain a `sorry` are written
in `lib/Scaffold.lean`, not `lib/Peephole.lean`**; the rule cannot enter `RULES`
until the proved theorem is *moved* into `Peephole.lean`. A rule with a
scaffolded theorem is recorded in a new `SCAFFOLDED_RULES` list (matcher
written and unit-tested, never run by the pass). `PENDING_RULES` keeps its
existing meaning: *proved* theorem, unsound matcher.

**S4. Touching `lib/ProofLib.lean` or `lib/X86.lean` is expensive and pinned.**
Adding an arm to `arm64_step` forces an `hne_` fact into every earlier
`work_step_*` theorem (the file will not elaborate otherwise), rebuilds
`ProofLib.olean`, invalidates every cached proof verdict
(`formal/lean.py::proof_verdict_key` covers the library digests), and moves the
pinned numbers in `test_formal_admitted.py` (`AXIOM_CLOSURE`, per-module
`native_decide`/`bv_decide` tallies) and `test_formal_axiom_closure_pinned.py`.
A step that edits either file re-measures those pins **and updates them in the
same commit, by reading the new measurement** — never widening a ceiling to
"whatever passes". Prefer putting new lemmas in `Scaffold.lean` (or a new small
module) over editing the giant files when the lemma does not have to be in them.

**S5. Worker rules (from `tools/formal_worker_rules.md`).** (Measured: any test that elaborates the library — `test_formal_proof_gaps`, `test_formal_admitted`, `test_formal_axioms`, `test_formal_sweep_truth` — peaks at ~8.2 GB, so it needs `--gb 24` (the `module` class), not 8; Lean-free tests such as `test_formal_peephole` run in 0.1 GB. A passing library test on a tree whose `.olean` is older than its source proves nothing: build with `formal.lean.ensure_library` first and read its output.) `export
PATH=/opt/homebrew/bin:$PATH` (python3 must be 3.14); verify with the *narrow*
`test_formal_*.py` files, each wrapped in `python3 tools/memslot.py --gb 8
--label t -- …`; **no `make gate` for formal work**; never `git checkout <path>`
or `git stash`; one step = one round = one commit, doc changes included; a step
that finishes a bug doc `git rm`s it in the same commit and runs
`python3 tools/dangling_doc_refs.py --ratchet` (that ratchet is already red on
the tree for reasons outside this plan — compare against the pre-step output and
make sure the step added nothing).

**S6. Step classes (who can do it).** The swarm routes by directory: `bugs/`
easy, `bugs/mid/` mid, `bugs/hard/` hard; `tools/pool.json`'s `iceman` slot
(20 workers) takes **mid and easy**; `opus`/`sonnet` take hard. Every step file
now carries a `Class:` line saying where it belongs. The rule for assigning it:
*iceman-class* means a worker with no design latitude can finish it from the
file alone — the files are named, the exact test command is given, every
decision is pre-made, and the "done when" is a command exit code. Anything with a
real open design question is split into a **decision/memo step (hard)** whose
output is a committed design section, and **execution steps (mid)** that consume
it. A step must also be small enough to land in one commit; if it is not, it is
split (`step-NNa`, `step-NNb`, …). The step numbers 01–28 are stable names;
suffix letters are the splits.

**S0. The tree is not green at the start (measured 2026-11-05).**
**`00a`** (umbrella; children `00c`-`00g`): `lib/ProofLib.lean` does not
elaborate — 143 errors at ~100 sites, a half-finished `callFunc2` migration,
the FP-register fields `d0`-`d7`, duplicated and fragment-corrupted FP step
theorems — and has not since Oct 18 (`9a6616e83` is the last version that
builds; a build is ~30 min, ~10 GB). `ProofLib.olean` on disk is from that old
source, so **every Lean-backed "DONE" in steps 01-05/12/18/27 was checked
against a stale binary and must be re-verified once `00a` is green.**
**`00b`**: `_STEP_CONDS` index drift. **`15a`**: monomorph baseline
(`import threading` etc.). Other workers edit this tree concurrently; a step
starts with `git status` and checks whether its deliverable already exists.

**S7. Honest numbering of what was stale in the first draft** (kept so a reader
of an old copy can translate): line `lib/X86.lean:2830` is `:3016`; the "two
`ProofLib` sorries at ~4510" do not exist; `test_formal_string_methods.py` is
`test_formal_str_methods.py`; `FORMAL_generic_monomorph_scope.md`,
`FORMAL_a_one_field_mutator_has_no_method_contract.md`,
`FORMAL_a_try_handler_arm_is_still_never_emitted.md`,
`FORMAL_trust_audit_2026-10-04.md` do not exist (their inventories must be
folded into the step that cites them, not "re-created"); and
`bugs/OPEN_WORK.md`'s generated table lost the rows for FORMAL docs that are
already gone (that edit is correct and uncommitted — commit it with the rest).

---

## Step index and order

Generated from the step files (`python3 tools/plan_index.py --write`;
`--check` also rejects a Depends id that names no file and any cycle).
**Class** says who can do it (S6): `easy`/`mid` = the `iceman` slot,
`hard` = opus/sonnet. A step with letters (`03b`) is a split of the original
numbered step; the numbers 01-28 are the first draft's names.

<!-- BEGIN generated by tools/plan_index.py -->

| step | status | class | size | depends | title |
|---|---|---|---|---|---|
| [`00a`](../bugs/plan/step-00a-repair-prooflib-splice.md) | OPEN | mid | M | 00c, 00d, 00e, 00f, 00g | `lib/ProofLib.lean` elaborates again (umbrella: gate for every Lean step) |
| [`00b`](../bugs/plan/step-00b-step-conds-index-drift.md) | OPEN | easy | S | none | `_STEP_CONDS` index drift — the STRB register-offset row sits in the middle of the table |
| [`00c`](../bugs/plan/step-00c-arm64state-fp-fields.md) | DONE | easy | S | none | struct literals that predate the FP register fields (`d0`-`d7`) |
| [`00d`](../bugs/plan/step-00d-callfunc2-migration.md) | DONE | mid | M | none | finish the `callFunc2` migration (`runF`, `evalFuncF`, the `runF_*` lemmas, the generator templates) |
| [`00e`](../bugs/plan/step-00e-contract-and-cmp-proofs.md) | DONE | mid | L | 00d | proofs broken by the shifted-register model — `arm64_step_cmp_reg_n31_reads_zero`, `while_lt_exit_contract_*` |
| [`00f`](../bugs/plan/step-00f-nonfp-work-step-proofs.md) | REGENERATED | mid | L | none | broken non-FP `work_step_*` proofs — `cmn`, `tst`, `ldur`, `stur`, `smulh`, `csel` |
| [`00g`](../bugs/plan/step-00g-fp-work-steps.md) | REGENERATED | mid | L | 00f | the FP `work_step_*` block — duplicates, timeouts, fragments |
| [`01a`](../bugs/plan/step-01a-scaffold-module.md) | CLAIMED | mid | M | 00a | `lib/Scaffold.lean` — the one home of scaffold `sorry` |
| [`01b`](../bugs/plan/step-01b-proof-gap-ledger.md) | CLAIMED | mid | M | 00a, 01a | the proof-gap ledger and its census test |
| [`02`](../bugs/plan/step-02-peephole-memory-lemmas.md) | CLAIMED | mid | S | 00a, 01a, 01b | the two memory lemmas the peephole store rules actually lack |
| [`03a`](../bugs/plan/step-03a-hne-chain-generator.md) | DONE | mid | S | none | a generator for the `hne_` negation chain of an `arm64_step` arm lemma |
| [`03b`](../bugs/plan/step-03b-arm64-movz-pair.md) | CLAIMED | mid | M | 00a, 01a, 01b, 03a | `arm64/movz_pair` — step lemma and rule theorem |
| [`03c`](../bugs/plan/step-03c-arm64-store-load.md) | CLAIMED | mid | M | 00a, 02, 03a | `arm64/store_load` — `STR Xt,[Xn,#o] ; LDR Xt,[Xn,#o]` |
| [`03d`](../bugs/plan/step-03d-arm64-mem-pair.md) | CLAIMED | mid | M | 00a, 02, 03c | `arm64/mem_pair` — duplicate `STR;STR` and `LDR;LDR` |
| [`04a`](../bugs/plan/step-04a-x86-mov-self-rev.md) | CLAIMED | easy | S | 00a, 01a, 01b | `x86_64/mov_self_rev` — `mov r, r` spelled `48 8b c0` |
| [`04b`](../bugs/plan/step-04b-x86-store-load.md) | CLAIMED | mid | M | 00a, 02, 01b | `x86_64/store_load` — `mov [b+d], r ; mov r, [b+d]` (no SIB; disp8 form first) |
| [`04c`](../bugs/plan/step-04c-x86-mem-pair.md) | CLAIMED | mid | M | 00a, 02, 04b | `x86_64/mem_pair` — duplicate store, duplicate load (no SIB) |
| [`04d`](../bugs/plan/step-04d-x86-imm-zero.md) | CLAIMED | mid | M | 00a, 01a, 01b | `x86_64/imm_zero` — `add r, 0` / `sub r, 0` with dead flags |
| [`05a`](../bugs/plan/step-05a-arm64-rule-registry.md) | CLAIMED | mid | M | 03b, 03c, 03d | register the arm64 rules the Lean side now proves |
| [`05b`](../bugs/plan/step-05b-x86-rule-registry.md) | CLAIMED | mid | M | 04a, 04b, 04c, 04d | register the x86-64 rules, and fix three latent soundness holes in their matchers |
| [`06a`](../bugs/plan/step-06a-arm64-ccmp-encoders.md) | OPEN | easy | S | none | arm64 `ccmp` encoders (register and immediate), byte-exact against `as` |
| [`06b`](../bugs/plan/step-06b-arm64-ccmp-model.md) | OPEN | mid | M | 00a, 00b, 06a | `ccmp` in the machine model: `arm64_step` arms, `_STEP_CONDS` rows, `_step_rhs`, `_regs_written` |
| [`06c`](../bugs/plan/step-06c-arm64-ccmp-lowering.md) | OPEN | hard | L | 06a, 06b | lower `if A and B:` (two integer comparisons) to `cmp` + `ccmp` + one `b.cond` |
| [`07a`](../bugs/plan/step-07a-arm64-csinc-family-model.md) | OPEN | mid | M | 00a, 00b | `csinc` / `csinv` / `csneg` in the machine model, step table and fuzzer |
| [`07b`](../bugs/plan/step-07b-arm64-csinc-family-lowering.md) | OPEN | hard | M | 07a | lower `a if c else ~a` to `csinv` (and `+1` / `-a` to `csinc`/`csneg` where no overflow trap is lost) |
| [`08a`](../bugs/plan/step-08a-arm64-blr-named-unmodelled.md) | OPEN | easy | S | none | name `BLR` in `_unmodelled_instruction` (the emitted indirect call has no step and no name) |
| [`08b`](../bugs/plan/step-08b-arm64-br-audit-scope.md) | OPEN | easy | S | none | `br` is emitted (the Mach-O stub) — fix the audit's scope and the stale "uncalled" claims |
| [`08c`](../bugs/plan/step-08c-arm64-indirect-call-design.md) | OPEN | hard | M | 08a | DESIGN MEMO — how the proof model treats `BLR` (indirect call) and `BR` |
| [`09`](../bugs/plan/step-09-arm64-extended-add-sub.md) | OPEN | mid | M | 00a, 00b | arm64 extended-register `ADD`/`SUB`/`SUBS(CMP)` with `UXTX` (the SP class), modelled, no lowering |
| [`10`](../bugs/plan/step-10-string-struct-collision.md) | OPEN | mid | M | 01a, 01b | the `String` frame-vs-`char *` collision (zero-argument `String()` used as a receiver) |
| [`11a`](../bugs/plan/step-11a-string-buffer-upper-lower.md) | OPEN | mid | M | 10 | the runtime string buffer (libc `strdup`, never freed) and `upper`/`lower` as its first clients |
| [`11b`](../bugs/plan/step-11b-string-strip-rstrip.md) | OPEN | mid | M | 11a | `strip()` / `rstrip()` on the runtime buffer |
| [`11c`](../bugs/plan/step-11c-chr-fold-and-remaining-methods.md) | OPEN | mid | S | 11a | `chr(<constant>)` folds; `replace`/`join`/the case-variants refuse naming the buffer correctly |
| [`12a`](../bugs/plan/step-12a-len-of-known-string.md) | OPEN | mid | M | 01a, 01b | `len(<string the image holds>)` is a numeral in the proof model; any other string `len` is refused; the post-extern theorem is not emitted for `strlen` |
| [`12b`](../bugs/plan/step-12b-strlen-contract-memo.md) | OPEN | hard | M | 12a, 01a, 01b | DECISION MEMO — the Lean contract for an extern whose result is the program's answer (`strlen`) |
| [`12c`](../bugs/plan/step-12c-strlen-contract.md) | OPEN | mid | M | 12a, 12b, 01a, 01b | Lean contract for `strlen` as the program's answer (extern contract) |
| [`13a`](../bugs/plan/step-13a-printf-text-fold.md) | OPEN | mid | M | 10 | `%<w>s`, `%-<w>s`, `%.<p>s` on a non-ASCII text the build can SEE are folded to the CPython answer |
| [`13b`](../bugs/plan/step-13b-subscript-literal-fold.md) | OPEN | mid | M | 10 | `<literal>[<int literal>]` on non-ASCII text folds to the one-character string |
| [`13c`](../bugs/plan/step-13c-runtime-unicode-memo.md) | OPEN | hard | M | 11a, 13a, 13b | DECISION MEMO — `%<w>s` / `%.<p>s` and `s[i]` on non-ASCII text the build CANNOT see |
| [`14a`](../bugs/plan/step-14a-restore-set-literal-dedup.md) | OPEN | easy | S | none | RESTORE the compile-time set-literal dedup that the `formal/model/` package split lost |
| [`14b`](../bugs/plan/step-14b-set-runtime-dedup-literal.md) | OPEN | mid | L | 14a | run-time distinctness for a set literal with non-canonical elements (`{x, x, 2}`), both backends |
| [`14c`](../bugs/plan/step-14c-set-add.md) | OPEN | mid | M | 14b | `set.add(x)` on both backends |
| [`14d`](../bugs/plan/step-14d-set-comprehension-dedup.md) | OPEN | mid | M | 14b | a set COMPREHENSION is distinct (`{x % 2 for x in range(6)}` has len 2) |
| [`14e`](../bugs/plan/step-14e-set-order-pin.md) | OPEN | easy | S | 14a, 14b, 14c, 14d | pin the set iteration order (insertion order) and re-word the `set_order` neutraliser; close the doc |
| [`15a`](../bugs/plan/step-15a-monomorph-baseline.md) | DONE | mid | M | none | repair the monomorph baseline (import errors, debug litter, stale test expectations) |
| [`15b`](../bugs/plan/step-15b-restore-aliased-import.md) | OPEN | mid | M | 15a | restore the ALIASED import of a template (`from m import Pair as P` then `P[Int]()`) |
| [`15c`](../bugs/plan/step-15c-restore-trait-bound-check.md) | OPEN | mid | M | 15a | restore the trait-bound conformance check on an instantiation |
| [`15d`](../bugs/plan/step-15d-consumer-declared-type-argument.md) | OPEN | mid | S | 15a | refuse, by name, a type argument declared only in the consumer's file |
| [`15e`](../bugs/plan/step-15e-pin-imported-parameter-annotation.md) | OPEN | easy | S | 15a | re-pin the imported-instantiation parameter annotation (value vs frame) |
| [`16a`](../bugs/plan/step-16a-bare-call-design-memo.md) | OPEN | hard | M | 15a | DESIGN MEMO — what a bare template call's type arguments may be inferred from |
| [`16b`](../bugs/plan/step-16b-consolidate-bare-inference.md) | OPEN | mid | M | 15a | fold the two copies of bare-call inference into one function (behaviour-preserving) |
| [`16c`](../bugs/plan/step-16c-matcher-keywords-defaults.md) | OPEN | mid | S | 16a, 16b | bare-call inference — keyword arguments and type-spelled defaults |
| [`16d`](../bugs/plan/step-16d-return-type-inference.md) | OPEN | mid | L | 16a, 16b | bare-call inference through declared types (the `dealloc(allocation^)` row) |
| [`16e`](../bugs/plan/step-16e-bound-resolution.md) | OPEN | mid | M | 16a, 16b | bare-call inference against a trait bound (the `FormatStruct(writer, ...)` row) |
| [`16f`](../bugs/plan/step-16f-reconcile-export-pins.md) | OPEN | easy | S | 16c, 16d, 16e | reconcile the two export pins and the refusal wording with the inference |
| [`17`](../bugs/plan/step-17-declared-init-construction.md) | DONE | easy | S | 15a | close out declared-`__init__` construction (it landed; pin it and fix the doc) |
| [`18a`](../bugs/plan/step-18a-frame-contract-memo.md) | OPEN | hard | M | 15a, 01b | DESIGN MEMO — what the one-field by-reference mutator's Lean contract may say |
| [`18b`](../bugs/plan/step-18b-frame-methods-restrict.md) | OPEN | mid | M | 18a | make `_frame_methods` classify only the shapes whose contract is true |
| [`18c`](../bugs/plan/step-18c-load-first-rule.md) | OPEN | mid | M | 18b | constant propagation learns the load-first rule for a by-reference receiver |
| [`18d`](../bugs/plan/step-18d-scaffold-writeback-contract.md) | OPEN | mid | M | 18a, 18c, 01b | scaffold the write-back contract (depth bound as a hypothesis, per-exit obligation as `sorry`) |
| [`19a`](../bugs/plan/step-19a-optional-unit-dylib.md) | OPEN | mid | M | 15a | build an OPTIONAL runtime unit (sqlite3 first) as a loadable dylib for the formal link line |
| [`19b`](../bugs/plan/step-19b-link-line-opt-in.md) | OPEN | mid | M | 19a | the formal link line opts into the optional unit a word-shaped call names |
| [`19c`](../bugs/plan/step-19c-sqlite-end-to-end.md) | OPEN | easy | S | 19b | a real sqlite3 word-shaped call through a formal executable, and the census numbers |
| [`20`](../bugs/plan/step-20-mlir-word-ops.md) | DONE | mid | S | 15a | close out the word-valued MLIR ops (the lowering landed; fix the 3 reds and the stale census) |
| [`22`](../bugs/plan/step-22-singleton-causes.md) | OPEN | mid | L | 15a, 16f, 17, 20 | the singleton direct causes — re-measure, then one verdict per row (LOOP STEP) |
| [`23`](../bugs/plan/step-23-host-modules.md) | CLAIMED | mid | S | 26 | host-module growth: the per-module round template and the ranked queue |
| [`23a`](../bugs/plan/step-23a-os-process-identity.md) | DONE | mid | S | 26 | os process identity: getpid, getppid, getuid, getpgid, cpu_count |
| [`23b`](../bugs/plan/step-23b-os-fs-metadata.md) | DONE | mid | M | 26 | os filesystem metadata: access + R_OK/W_OK/X_OK/F_OK, utime, symlink, link, mkfifo, umask |
| [`23c`](../bugs/plan/step-23c-os-stat-times.md) | DONE | mid | M | 26 | os.path.getmtime/commonpath/sep and os.stat/lstat as per-field functions |
| [`23d`](../bugs/plan/step-23d-os-fd-io.md) | CLOSED AS 'NOT PROVIDED' | mid | M | 26 | os file-descriptor I/O: close, read, write, fsync, ftruncate, dup2, pipe, O_*/SEEK_SET constants |
| [`23e`](../bugs/plan/step-23e-os-process-and-refusals.md) | DONE | mid | S | 26, 23a | os signals/process-group wrappers and the documented NOT-PROVIDED table |
| [`24`](../bugs/plan/step-24-x86-arch-drift.md) | DONE | easy | S | none | x86-64 arch drift is mostly ALREADY CLOSED: pin it and correct the doc |
| [`25`](../bugs/plan/step-25-unrepresentable-types.md) | CLAIMED | mid | S | none | `Error` stays unrepresentable: make the refusal true, pin it on both backends |
| [`26`](../bugs/plan/step-26-host-exception-convention.md) | DONE | mid | M | none | one discoverable host-module failure convention (`hoststatus`) |
| [`27a`](../bugs/plan/step-27a-eh-design-memo.md) | CLAIMED | hard | M | 25 | EH runtime design memo (exception object storage, `as e`, superclass matching) |
| [`27b`](../bugs/plan/step-27b-try-model-translation.md) | DONE | mid | M | 27a | `TryStmt` in the semantic model (`arm64_proof_gen.py`): the sound flat slice |
| [`27c`](../bugs/plan/step-27c-landing-pad-tables.md) | DONE | mid | M | 27a | landing-pad / personality data structures (pure Python table + test, NO codegen change) |
| [`28`](../bugs/plan/step-28-absval-frame-peel.md) | CLAIMED | mid | M | 00a | `absval` frame-peel `K` — verify the same-day fix, pin it with a Lean-free test, then close or localise |

**78 step files:** 13 easy, 57 mid, 8 hard. Status: claimed 16, closed as 'not provided' 1, done 15, open 44, regenerated 2. (Generated by `python3 tools/plan_index.py --write`; do not edit by hand.)

<!-- END generated by tools/plan_index.py -->

**Waves**: see the section at the end of this file.

---

## Detailed steps

There is no second copy of the step text here. **The step files are the single
source** (`bugs/plan/step-*.md`); the first draft duplicated each step in this
file and in its own file, and the two had already drifted (CLAUDE.md: one
implementation, not two). The index above is generated from the step files'
header lines by `tools/plan_index.py`, and `--check` fails if it is stale.

---

## Verification and rollout

Every step's commit runs, at minimum:

```
python3 test_formal.py --backend arm64           # corpus, arm64
python3 test_formal.py --backend x86_64          # corpus, x86-64
python3 test_arm64_encoders.py                    # when an encoder is added
python3 test_arm64_emission.py                    # when a lowering is added
python3 test_formal_peephole.py                   # when the pass changes
python3 test_formal_call_proof_gen.py             # when the proof model changes
python3 test_formal_proof_gaps.py                 # step-01 census, always
python3 tools/formal_doc_index.py --check         # the queue stays current
python3 tools/dangling_doc_refs.py --ratchet      # no new dangling citations
```

Run each under `python3 tools/memslot.py --gb 8 --label t --` where the build is
memory-heavy (a first pass over many declared gaps may belong to whoever can
run the corpus).

**When a step closes a `FORMAL_*.md` entirely:** update that doc's top-of-file
status, or delete it if the project's rule applies (`CLAUDE.md`: a fixed bug doc
is deleted, not kept with a history), and rewrite every citation. Re-run
`tools/dangling_doc_refs.py --ratchet` and `tools/formal_doc_index.py --write`.

## What this plan deliberately does not do

- It does not prove anything. Proofs are follow-up commits; the `sorry`/`admit`
  holes are the deliverable here.
- It does not unify the two backends. Shared *answers* go in `formal/model/`;
  instruction selection stays per backend.
- It does not touch a `bugs/FORMAL_*.md` row whose verdict is "true limit,
  permanent" (`std/sys/info.mojo`'s `_TargetType`, `current_target` as a value,
  `target_has_feature`, the MLIR dialect attributes, the `_assembly.mojo`
  inline-asm module). Those are read as facts about the modules, not as work;
  the steps above say so where it matters (step-20, step-22).

## Not in this plan: the bare `comptime <expr>` diagnostic

The first draft's step 21 (give the bare spelling `comptime expr` the
"unavailable in compiled mode" diagnostic, `FORMAL_known_limits.md` §7) is
**left to the integrator**. It changes `mojo/backend_gimple/`, which CLAUDE.md
puts behind a full `make gate`, so no worker in this plan owns it. The number 21
is retired; the file is removed.

## Where the work stands (hand-written; the table above is generated)

Updated 2026-11-05 as steps finish. **Read the Status column literally:**
`DONE` = carries its own dated, measured Status; `CLAIMED` = stamped "verified by
agent" by the first execution wave WITHOUT a measurement, so treat as unproven;
`REGENERATED` = rebuilt but waiting on a full-library build; `OPEN` = not started.

* **Critical path: `lib/ProofLib.lean` must elaborate (step `00a`).** Repaired
  across `00c`-`00g`; a prefix build of lines 1..5400 has 0 errors and a full
  build of the regenerated tail had 24 errors, all explained and fixed; a final
  full-file build is the verification and is still running when this was
  written. Until it is green, every `CLAIMED` Lean-backed step (01a, 01b, 02,
  03b-d, 04a-d, 05a-b, 12, 18, 27a) is unverified, and the `.olean`s on disk are
  from the Oct-18 source.
* **Python / hostmod work verified and committed:** 14a (set dedup), 15a (monomorph
  suite 60/0), 17, 20, 23a-e (the `os` hostmod: process identity, fs metadata,
  stat times, kill/setsid, and the by-name NOT PROVIDED table), 24, 26, 27b, 27c,
  and the review fixes below.
* **Bugs found by checking the "DONE" claims** (all fixed, each with a test that
  fails on the old code): unsound x86-64 peephole memory matchers; `(b"", 1)`
  deleting the FIRST instruction so `store_load` kept the load; `var s = "lit"`
  recorded as a `comptime` constant (broke 42 of 92 hostmods); x86-64 signed `<<`
  undone with a second `<<` (every `x <<= n` trapped); x86-64 `_emit_shift_reg`
  saving its amount in R12, a register-allocated LOCAL (every `stat` field came
  back wrong, `os.path.getsize` -1); the lost `Template.<attr>` ambiguity refusal;
  a `#` inside a backtick literal read as a comment; a brittle `tbz` count over
  data decoded as code.
* **Still open and known:** `subprocess` (14-argument struct return, 90/92
  hostmods), `getmtime -> Float64` (no int->double on this path; `getmtime_ns`
  instead), `commonpath`, the file-descriptor functions (no writable-descriptor
  producer), the Lean arms for `ccmp`/`csinc`/`csinv`/`csneg`/extended-register
  (the `_STEP_CONDS` rows exist without Lean arms: `check_step_conds` warns),
  steps 06c, 07b, 08c, 10, 11a-c, 12b-c, 13a-c, 14b-e, 16a-f, 18a-d, 19a-c, 22.
* **Found 2026-11-06 while running the regressions:** `strip`/`rstrip` on an
  unfoldable receiver (11a/11b) are now correct on both backends
  (`test_formal_str_trim_runtime.py`); the `str(<non-string>)` refusal path
  crashed on a nonexistent `BOOL_KIND` import (fixed); x86-64 traps `<<`/`**`
  overflow and arm64 still wraps (pinned as a divergence in
  `test_formal_int_semantics.py`); x86-64 grows a loop-appended list on a heap
  blob and arm64 stops loudly (`list_append_overflow_is_loud`) — a parity item.
  `test_formal_run.py` still has stale "refused" rows for constructs that now
  build (`upper`, f/t-strings) and changed refusal wording on the vararg and
  set-comprehension rows.
* **Not run:** `test_formal_admitted.py` / `test_formal_axiom_closure_pinned.py`
  (need the library build; pins will move), the `make gate` bucket.

## Waves

Parallel groups, derived from the Depends column (recompute when the index
changes; `tools/plan_index.py --check` rejects cycles). Everything in one wave
can run at the same time on different workers.

| wave | steps | note |
|---|---|---|
| 0 | `00a`, `00b`, `15a`, `03a`, `06a`, `08a`, `08b`, `14a`, `24`, `25`, `26` | no dependencies. `00a` unblocks all Lean work. |
| 1 | `01a`, `28`, `09`, `07a`, `06b`, `14b`, `15b-e`, `16a`*, `16b`, `17`, `19a`, `20`, `23`, `23a-d`, `27a`* | `*` = hard (opus/sonnet). |
| 2 | `01b`, `10`, `12a`, `06c`*, `07b`*, `08c`*, `14c`, `14d`, `16c-e`, `18a`*, `19b`, `23e`, `27b`, `27c` | |
| 3 | `02`, `04a`, `04d`, `11a`, `13a`, `13b`, `12b`*, `18b`, `19c`, `14e`, `16f` | |
| 4 | `03b`, `03c`, `04b`, `11b`, `11c`, `13c`*, `18c`, `22` | |
| 5 | `03d`, `04c`, `18d` | |
| 6 | `05a`, `05b` | peephole rules register only the theorems proved by then |

**Iceman-suitable** (`easy` + `mid`, no open design question): everything not
marked hard. **Hard (memo or deep Lean):** `06c`, `07b`, `08c`, `12b`, `13c`,
`16a`, `18a`, `27a`. Each hard step's output is a committed decision that
unblocks mid steps; none of them is on the critical path of the peephole
work (`00a → 01 → 02 → 03/04 → 05`), which is entirely iceman-class.

## Review log (2026-11-05, after the first execution wave)

Independent re-check of what workers marked "DONE (verified by agent)". Not
everything was; what was found and fixed, so the markers are read with it:

- `x86_64` memory matchers (`_x_mem_pair`, `_x_store_load`) were unsound: the
  decoder overwrites `rm` with the BASE register for a memory operand, so the
  store pair never compared the stored register and store-load compared the base
  with the load's destination. Fixed; `TestX86MemoryMatchers` drives the matchers
  directly (the earlier "decline" tests ran `X86_RULES`, which excludes the
  scaffolded rules, and passed vacuously).
- `(b"", 1)` from a rule means "delete the window's FIRST instruction"; the arm64
  and x86 `store_load` matchers used it to mean "delete the second", i.e. they
  deleted the STORE and kept the load. New `KEEP_FIRST` return; arm64 end-to-end
  tests read back which instruction survives.
- Both codegens recorded every `var s = "lit"` in `_comptime_vals`, so any later
  reassignment of a string variable was rejected as "assignment to comptime
  binding". It broke 42 of 92 hostmods (`out = ...` in `os/_syscalls.mojo`);
  removed, 90/92 build. `subprocess` (a 14-argument function returning a struct)
  is a separate, older limit.
- `lib/Peephole.lean` had its whole "x86-64 rules" section twice and an orphan
  doc comment; x86 scaffold theorems named by registered rules did not exist
  anywhere (steps 04a-04c "DONE"); both fixed, and a test now fails if a
  scaffolded rule names a theorem that is neither ledgered nor declared.
- Resource note: tests that elaborate the library peak at ~8.2 GB; use
  `--gb 24`.
- Still true after this pass: `test_formal_x86_64_parity` has one failure
  (`aug_every_operator`, an overflow trap on `<<`) unrelated to this plan.
