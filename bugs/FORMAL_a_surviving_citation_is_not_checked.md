# Two documents that own no code still cite the deleted narrow-parameter doc

**Area:** documentation only. Found 2026-10-05 while deleting the narrow-typed
parameter's document (`FORMAL_arm64_a_narrow_typed_parameter_makes_the_universal_
contract_false`, named **without** its `bugs/` prefix on purpose — see the last
paragraph) with its fix.

**Status: the INSTRUMENT is fixed; three rows in two documents are not, and both
of those documents are another worker's live claim.** The gap this document is
really about — a citation spelled without `bugs/` was measured and never
judged, so a deleted document's bare citations survived its delete with
`--ratchet` green — is closed: `tools/dangling_doc_refs.py` now holds the bare
class to a per-file ceiling of its own (`BARE_BASELINE`), so a delete that
strands one fails **at the delete**. `test_suite.py`'s `dangling refs:` group
gains three checks, one of which plants a citation in a scratch file and asks
`ratchet_verdict` — the function `--ratchet` itself calls — about both halves of
the corpus at once, so "it is wired to a verdict" is measured rather than
asserted. What is left is the table below, and it is 3 rows rather than 4:
`bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md` has been rewritten and
says so. **The `bugs/`-prefixed floor of ONE this document used to record is
gone**: `tools/dangling_refs_baseline.py` was regenerated after that rewrite and
its only remaining entry is `test_suite.py`'s own six negative controls.

**And the file this one is ABOUT is flagged by its own subject.** The ratchet
went red on *this* document the moment it was written, because naming the
deleted path with a `bugs/` prefix is itself a citation of a deleted document —
the tool is right and the fix is the spelling, not the deletion. That is also the
cleanest possible demonstration of the gap: the mechanism that catches a stale
citation caught the document explaining stale citations. It is still red on line
38 for the same reason — that row is one of the three below, spelled without a
prefix because the OTHER documents spell it that way, and `BARE_BASELINE` now
records it at 1.

It is NOT a dangling citation in the ratchet's sense — `tools/dangling_doc_refs.py
--ratchet` is green — which is the point of filing it. The ratchet checks that no
file *gains* a citation of a deleted document; it does not check that a
surviving citation still describes the tree. So four rows across three documents
outside this worker's claim kept a reference to a document that no longer exists,
and nothing reported it.


## What is stale, and where

| file | line | what it says now | whose claim |
|---|---|---|---|
| ~~`bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md`~~ | ~~40~~ | **rewritten** — it now records the resolution ("RESOLVED as of 2026-10-05 … the document that owned them was deleted with the fix") and says the citation "that used to sit here dangled". Verified by reading it; nothing cites the name there. | was `formal28-3`; unclaimed now |
| `bugs/FORMAL_proof_coverage_census_2026-10-03.md` | 843 | goal row 5, `⊢ (if sKey a ≤ sKey b then 1 else 0) = …` or a `t32s (t8s n) = n` round trip, owned by the deleted doc | **`formal29-4`** |
| `bugs/FORMAL_eighteen_examples_have_no_accepted_proof_and_seven_are_declared.md` | 64 | a per-stem row reading `sgt8 | lean-rejected | … | FORMAL_arm64_a_narrow_typed_parameter_makes_the_universal_contract_false.md` | **`formal42-3`** |
| `bugs/FORMAL_eighteen_examples_have_no_accepted_proof_and_seven_are_declared.md` | 206 | prose pointing at the deleted doc | **`formal42-3`** |

**The three that remain are false about the tree, and the same way.** The defect
was `def sgt8(n: Int8)` narrowing the incoming word (`SXTB` then `SXTW`) and the
CFG walk then asking Lean for `⊢ t32s (t32u (t8s n)) = n` — FALSE over the
theorem's unconstrained `n`, so Lean **rejected** the file with no `sorry`
anywhere. The universal theorem now carries the range hypothesis that obligation
needs (`nw : n < 128`, from `formal/arm64_proof_gen.py::_narrow_param_bound`),
and the truncation discharges against it.

Measured, both ends:

```
before:  [1/3] FAIL sgt8   [2/3] FAIL sle8   [3/3] FAIL ug8   PASS=0 FAIL=3
after:   [1/4] PASS sgt8   [2/4] PASS sle8   [3/4] PASS ug8   [4/4] PASS n8
```

So `sgt8`, `sle8`, `ug8` and `n8` are four examples that were **lean-rejected**
and are now **typechecked with zero `sorry`**. Note the residual goal's spelling
also moved: those documents record `t32s (t8s n)` where this tree's generator
emits `t32s (t32u (t8s n))` (the extra `t32u` is the 32-bit intermediate of
`SXTB`-then-`SXTW`), and `ug8`'s is the different `t8u n = n` entirely. That
figure is the fix's own measurement and has not been re-run here — a Lean proof
run is not a bounded worker's to start — but the fix it describes is in the tree
and is pinned by `test_formal_call_proof_gen.py::TestANarrowTypedParameterGetsItsRange`.

## Why the three rows are not fixed here

All three are inside documents held by **another worker's LIVE claim**, and the
standing rule is to report an area another worker holds rather than edit it.
`python3 tools/control.py claims` puts
`FORMAL_eighteen_examples_have_no_accepted_proof_and_seven_are_declared.md` on
`formal42-3` and `FORMAL_proof_coverage_census_2026-10-03.md` on `formal29-4`.
The fourth row's file is fixed and is listed above only so the count is honest.

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

**The instrument gap this is really about**, which is now closed rather than
described: `tools/dangling_doc_refs.py` proved the corpus of citations can only
shrink, and nothing proved a surviving citation was still TRUE — a citation
survives its subject. It could not even see this document's own four rows, all
four of which are spelled without the `bugs/` prefix. `bare_find` has reported
that class since 2026-10-05 and `BARE_REF`'s comment held it out of the ratchet
because "a ledger for it would have to bless every existing sentence" — which
stopped being true when the `deleted_convention` skip landed and gave the finder
the convention the objection had asked for. So `BARE_BASELINE` exists,
`--write-baseline` writes both tables in one invocation (so the sanctioned
command cannot leave half the ratchet vacuous), and `--ratchet` consults both
through one function, `ratchet_verdict`. The three checks in `test_suite.py` are
that claim's teeth: the table exists and is green on arrival; the same reader
judges it that judges the prefixed class; and a planted bare citation of a
document that is nowhere is a GAIN in the bare half of that one function and
nothing at all in the prefixed half — which is this defect, stated as a
difference between two halves of one function instead of as prose.

## Reproducing

```console
$ python3 tools/dangling_doc_refs.py --ratchet     # green — and it now SEES
                                                 # this class; before, this
                                                 # document's own four rows
                                                 # were invisible to it
$ grep -rn FORMAL_arm64_a_narrow_typed_parameter bugs/ --include=*.md
```

Four hits: this document's line 38 and the three rows in the two claimed files
above. `bugs/OPEN_WORK.md` does not list it — its queue is generated from the
documents that exist, so a deleted one cannot appear.
