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
| `bugs/FORMAL_absval_proof_does_not_check.md` | a formerly-passing arm64 example whose proof now fails on a frame-peel address |
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
   never ignored; `step-28` is the specific instance (`absval`), and the general
   rule is `FORMAL_absval_proof_does_not_check.md`'s "a formerly-passing
   example that now fails is a regression".

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

**S5. Worker rules (from `tools/formal_worker_rules.md`).** `export
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

| step | class | size | depends | title |
|---|---|---|---|---|
| [`01a`](../bugs/plan/step-01a-scaffold-module.md) | mid | M | none | `lib/Scaffold.lean` — the one home of scaffold `sorry` |
| [`01b`](../bugs/plan/step-01b-proof-gap-ledger.md) | mid | M | 01a | the proof-gap ledger and its census test |
| [`02`](../bugs/plan/step-02-peephole-memory-lemmas.md) | mid | S | 01a, 01b | the two memory lemmas the peephole store rules actually lack |
| [`03a`](../bugs/plan/step-03a-hne-chain-generator.md) | mid | S | none | a generator for the `hne_` negation chain of an `arm64_step` arm lemma |
| [`03b`](../bugs/plan/step-03b-arm64-movz-pair.md) | mid | M | 01a, 01b, 03a | `arm64/movz_pair` — step lemma and rule theorem |
| [`03c`](../bugs/plan/step-03c-arm64-store-load.md) | mid | M | 02, 03a | `arm64/store_load` — `STR Xt,[Xn,#o] ; LDR Xt,[Xn,#o]` |
| [`03d`](../bugs/plan/step-03d-arm64-mem-pair.md) | mid | M | 02, 03c | `arm64/mem_pair` — duplicate `STR;STR` and `LDR;LDR` |
| [`04a`](../bugs/plan/step-04a-x86-mov-self-rev.md) | easy | S | 01a, 01b | `x86_64/mov_self_rev` — `mov r, r` spelled `48 8b c0` |
| [`04b`](../bugs/plan/step-04b-x86-store-load.md) | mid | M | 02, 01b | `x86_64/store_load` — `mov [b+d], r ; mov r, [b+d]` (no SIB, disp8/disp32/none) |
| [`04c`](../bugs/plan/step-04c-x86-mem-pair.md) | mid | M | 02, 04b | `x86_64/mem_pair` — duplicate store, duplicate load (no SIB) |
| [`04d`](../bugs/plan/step-04d-x86-imm-zero.md) | mid | M | 01a, 01b | `x86_64/imm_zero` — `add r, 0` / `sub r, 0` with dead flags |
| [`05a`](../bugs/plan/step-05a-arm64-rule-registry.md) | mid | M | 03b, 03c, 03d | register the arm64 rules the Lean side now proves |
| [`05b`](../bugs/plan/step-05b-x86-rule-registry.md) | mid | M | 04a, 04b, 04c, 04d | register the x86-64 rules, and fix three latent soundness holes in their matchers |

**13 step files:** 1 easy, 12 mid, 0 hard. (Generated by `python3 tools/plan_index.py --write`; do not edit by hand.)

<!-- END generated by tools/plan_index.py -->

**Waves** (what can run in parallel; recomputed by hand when the index changes):
see the "Waves" section at the end of this file.

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

Run each under `python3 tools/memslot.py --gb 8 --label t --` where the doc says
the build is memory-heavy (`FORMAL_absval_proof_does_not_check.md` is explicit
that a first pass over the 31 declared gaps belongs to whoever can run the
corpus).

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
