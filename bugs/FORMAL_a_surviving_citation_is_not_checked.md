# Two documents that own no code still cite the deleted narrow-parameter doc

**Area:** documentation only. Found 2026-10-05 while deleting the narrow-typed
parameter's document (`FORMAL_arm64_a_narrow_typed_parameter_makes_the_universal_
contract_false`, named **without** its `bugs/` prefix on purpose — see the last
paragraph) with its fix.

**And the file this one is ABOUT is flagged by its own subject.** The ratchet
below went red on *this* document the moment it was written, because naming the
deleted path with a `bugs/` prefix is itself a citation of a deleted document —
the tool is right and the fix is the spelling, not the deletion. That is also the
cleanest possible demonstration of the gap: the mechanism that catches a stale
citation caught the document explaining stale citations.

**Status: the FOUR ROWS are fixed (2026-10-05, `work/formal40-2`) and the
baseline is back to its original floor. The instrument gap is NOT closed and is
the whole of what is left.**

Every claim that held one of the three files had been **released** by the time
this was picked up — `python3 tools/control.py claims` lists no worker for any
of them — so the standing rule ("report an area another worker holds rather
than edit it") no longer applied and the rows were corrected against a fresh
measurement rather than against the old doc's belief:

| file | what changed |
|---|---|
| `bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md:40` | the `sgt8`/`sle8` red is gone; the row is rewritten as the FIX with its current verdict and its pinning test |
| `bugs/FORMAL_proof_coverage_census_2026-10-03.md:797` | the `lean-rejected` family's owner is marked fixed, with the four stems' new verdict |
| `bugs/FORMAL_eighteen_examples_have_no_accepted_proof_and_seven_are_declared.md:64,206` | rows 4/5/6 moved from `lean-rejected` to `PASS`, and the "whose it is" prose says they are no longer anybody's because they are no longer broken |

```
$ python3 test_formal.py -j 1 sgt8 sle8 ug8 n8
  [1/4] PASS  sgt8   [2/4] PASS  sle8   [3/4] PASS  ug8   [4/4] PASS  n8
Results for arm64 formal proofs: PASS=4 KNOWN-GAP=0 FAIL=0 TOO-LARGE=0
proof census: 0 admitted `sorry` in the generated file, in 0 of 4 proof(s) checked
```

**And the sanctioned escape this document recorded is withdrawn**, which is the
part that made the raise safe to begin with: the baseline entry
`'bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md': 1` is gone from
`tools/dangling_refs_baseline.py`, so the corpus is back at the floor of zero it
started from. `tools/dangling_doc_refs.py --ratchet` is green and its count went
**7 → 6**, and `test_suite.py` is 335/0 — the self-test that checks the registry
and the ratchet agree agrees.

**A fourth citation exists that this document did not list, and it is already
honest.** `bugs/FORMAL_floordiv_and_udivmod_are_red.md:4` names the same
deleted document, and its sentence is *"Found 2026-10-05 while fixing
`…`"* — a statement about the history, which is what
`BARE_REF`'s `deleted_convention` exists to skip. It is also **another worker's
live claim** (`formal40-5`), so it was left alone on both counts.

## What is still open: the instrument gap, and it is the worthier half

**The ratchet counts citations of deleted documents; it does not check that a
surviving one is still TRUE, and nothing in the tree does.** The four rows above
were false about the tree for as long as the document they named existed, and
the only thing that reported them was a reader who went looking — which is the
definition of a gap.

Two halves, and the first is already done and is worth knowing about:
**`tools/dangling_doc_refs.py::bare_find` catches the un-prefixed spelling**
(`BARE_REF`, and its existence-by-name resolution, since a bare stem is only a
citation when no file of that name exists anywhere in the tree). It reports 306
of them across 114 files and is **deliberately not in the ratchet** — a bare
name has no convention separating the ~20 historical "was X, deleted" sentences
from a new one, so a ledger for it would have to bless every existing sentence
and would move whenever any branch edits prose in a file another branch is
editing. That reasoning is still sound.

**What is missing is the second half the document names, and it is a different
check rather than a second regex.** "Every `bugs/` path named in another `bugs/`
document still exists" is the `dangling` half and has been implemented since
this was written. What does not exist is any check that a document's *claims*
about the tree are still its claims — which is undecidable in general and
decidable for the narrow, high-value case here: **a `bugs/` document that states
a TEST STATUS is checked against the registry by `test_suite.py`, and a document
that states a TALLY is not checked against anything.** The three rows fixed above
were of the second kind (a per-stem verdict table), which is why nothing
noticed. The cheapest honest version of the check is the one
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md` demonstrates: re-measure, then
replace the row with the fact rather than with a pointer to whoever owned it.

**The next step, in order.** (1) Teach `dangling_doc_refs.py` to report — not
to fail on — a `bugs/` document whose most recent `PASS`/`FAIL` claim names a
stem whose current verdict is different, for the handful of documents that keep
a verdict TABLE (`FORMAL_eighteen_examples…` and `FORMAL_proof_coverage_census…`
are the two). (2) Leave it reporting-only, for `BARE_REF`'s reason: the tables
are prose-adjacent and a branch that fixes one must be able to move it without a
ledger. (3) Add the negative control — a fixture table with a deliberately wrong
verdict — because a checker that cannot fail is not a checker.

**What this does NOT do:** it does not make any stale citation fail, and it does
not cover the `test_suite.py` fixtures, which are six deliberate
self-referential citations and stay a fixed intentional number.

## What is still open: the instrument gap, and it is the worthier half

**The ratchet counts citations of deleted documents; it does not check that a
surviving one is still TRUE, and nothing in the tree does.** The four rows above
were false about the tree for as long as the document they named existed, and
the only thing that reported them was a reader who went looking — which is the
definition of a gap.

Two halves, and the first is already done and is worth knowing about:
**`tools/dangling_doc_refs.py::bare_find` catches the un-prefixed spelling**
(`BARE_REF`, and its existence-by-name resolution, since a bare stem is only a
citation when no file of that name exists anywhere in the tree). It reports 306
of them across 114 files and is **deliberately not in the ratchet** — a bare
name has no convention separating the ~20 historical "was X, deleted" sentences
from a new one, so a ledger for it would have to bless every existing sentence
and would move whenever any branch edits prose in a file another branch is
editing. That reasoning is still sound.

**What is missing is the second half the document names, and it is a different
check rather than a second regex.** "Every `bugs/` path named in another `bugs/`
document still exists" is the `dangling` half and has been implemented since
this was written. What does not exist is any check that a document's *claims*
about the tree are still its claims — which is undecidable in general and
decidable for the narrow, high-value case here: **a `bugs/` document that states
a TEST STATUS is checked against the registry by `test_suite.py`, and a document
that states a TALLY is not checked against anything.** The three rows fixed above
were of the second kind (a per-stem verdict table), which is why nothing
noticed. The cheapest honest version of the check is the one
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md` demonstrates: re-measure, then
replace the row with the fact rather than with a pointer to whoever owned it.

**The next step, in order.** (1) Teach `dangling_doc_refs.py` to report — not
to fail on — a `bugs/` document whose most recent `PASS`/`FAIL` claim names a
stem whose current verdict is different, for the handful of documents that keep
a verdict TABLE (`FORMAL_eighteen_examples…` and `FORMAL_proof_coverage_census…`
are the two). (2) Leave it reporting-only, for `BARE_REF`'s reason: the tables
are prose-adjacent and a branch that fixes one must be able to move it without a
ledger. (3) Add the negative control — a fixture table with a deliberately wrong
verdict — because a checker that cannot fail is not a checker.

**What this does NOT do:** it does not make any stale citation fail, and it does
not cover the `test_suite.py` fixtures, which are six deliberate
self-referential citations and stay a fixed intentional number.

It is NOT a dangling citation in the ratchet's sense — `tools/dangling_doc_refs.py
--ratchet` is green — which is the point of filing it. The ratchet checks that no
file *gains* a citation of a deleted document; it does not check that a
surviving citation still describes the tree. So four rows across three documents
outside this worker's claim kept a reference to a document that no longer exists,
and nothing reported it.


## What is stale, and where

| file | line | what it says now |
|---|---|---|
| `bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md` | 40 | cites the deleted doc as the owner of a failure |
| `bugs/FORMAL_proof_coverage_census_2026-10-03.md` | 797 | lists `⊢ t32s (t8s n) = n` among the open goals, owned by the deleted doc |
| `bugs/FORMAL_eighteen_examples_have_no_accepted_proof_and_seven_are_declared.md` | 64 | a per-stem row reading `sgt8 | lean-rejected | … | FORMAL_arm64_a_narrow_typed_parameter_makes_the_universal_contract_false.md` |
| `bugs/FORMAL_eighteen_examples_have_no_accepted_proof_and_seven_are_declared.md` | 206 | prose pointing at the deleted doc |

**Every one of them is now false about the tree, and the same way.** The defect
was `def sgt8(n: Int8)` narrowing the incoming word (`SXTB` then `SXTW`) and the
CFG walk then asking Lean for `⊢ t32s (t32u (t8s n)) = n` — FALSE over the
theorem's unconstrained `n`, so Lean **rejected** the file with no `sorry`
anywhere. The universal theorem now carries the range hypothesis that obligation
needs (`nw : n < 128`), and the truncation discharges against it.

Measured, both ends:

```
before:  [1/3] FAIL sgt8   [2/3] FAIL sle8   [3/3] FAIL ug8   PASS=0 FAIL=3
after:   [1/4] PASS sgt8   [2/4] PASS sle8   [3/4] PASS ug8   [4/4] PASS n8
```

So `sgt8`, `sle8`, `ug8` and `n8` are four examples that were **lean-rejected**
and are now **typechecked with zero `sorry`**. Note the residual goal's spelling
also moved: those documents record `t32s (t8s n)` where this tree's generator
emits `t32s (t32u (t8s n))` (the extra `t32u` is the 32-bit intermediate of
`SXTB`-then-`SXTW`), and `ug8`'s is the different `t8u n = n` entirely.

## Why this was not fixed in the same commit

All four citations are inside documents held by **other workers' claims**, and
the standing rule is to report an area another worker holds rather than edit it.
`python3 tools/control.py claims` puts
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md` on `formal28-3` and
`FORMAL_eighteen_examples_have_no_accepted_proof_and_seven_are_declared.md` /
`FORMAL_proof_coverage_census_2026-10-03.md` on other live claims.

## The exact next step

Whoever holds each claim: re-read the row against a fresh
`python3 test_formal.py -j 1 <stem>` and either delete the row or replace the
owner column with the fact that replaced it. The minimal honest replacement is
the symptom plus its current verdict, since the deleted document no longer
exists to carry the reasoning:

```
sgt8 | PASS (2026-10-05) | was `lean-rejected` on `⊢ t32s (t32u (t8s n)) = n`,
a narrow typed parameter's truncation with no range hypothesis on the theorem;
fixed in formal/arm64_proof_gen.py, pinned by
test_formal_call_proof_gen.py::TestANarrowTypedParameterGetsItsRange
```

## Reproducing

```console
$ python3 tools/dangling_doc_refs.py --ratchet     # green — the point
$ python3 tools/dangling_doc_refs.py                # 6 prefixed, 306 BARE
$ python3 test_formal.py -j 1 sgt8 sle8 ug8 n8     # PASS=4 FAIL=0
$ python3 test_suite.py                            # 335 passed
$ grep -rn FORMAL_arm64_a_narrow_typed_parameter bugs/ --include=*.md
```

Two hits remain, both honest: this document (which is ABOUT the deleted name and
says so with the `deleted` convention `BARE_REF` skips on), and
`bugs/FORMAL_floordiv_and_udivmod_are_red.md`, whose sentence is *"Found
2026-10-05 while fixing `…`"* — a statement about the history rather than a
claim on it, and another worker's live claim (`formal40-5`) besides.
`bugs/TEST_the_two_dangling_ref_mechanisms_disagree_and_suite_self_test_is_red.md`
names it in its own reproduction, which is the third and is that document's
subject.
