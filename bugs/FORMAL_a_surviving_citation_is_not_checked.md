# Two documents that own no code still cite the deleted narrow-parameter doc

**Area:** documentation, plus one line of `tools/dangling_doc_refs.py`. Found
2026-10-05 while deleting the narrow-typed parameter's document — named in this
file's own table below, and **without** its `bugs/` prefix on purpose, which is
what put this file in the bare-citation census (see §"What landed").

**And the file this one is ABOUT is flagged by its own subject.** The ratchet
below went red on *this* document the moment it was written, because naming the
deleted path with a `bugs/` prefix is itself a citation of a deleted document —
the tool is right and the fix is the spelling, not the deletion. That is also the
cleanest possible demonstration of the gap: the mechanism that catches a stale
citation caught the document explaining stale citations.

**Status: the INSTRUMENT half is FIXED (2026-10-05, this file's own claim). The
four stale rows are still stale and still sit in other workers' documents — see
§"What landed" and §"What is still open".**

The floor of ONE this file recorded is **GONE**, and it is gone because the
instrument could not see that it was stale — which is the whole of §"The
instrument gap". `tools/dangling_doc_refs.py --ratchet --write-baseline` had
raised `bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md: 0 → 1` so the gate
stayed green, on the reasoning that a worker who fixes the citation should drop
the entry rather than leave it. **Nothing could tell that the worker had.**
`stale_baseline_entries` read `ledger_verdicts`, which is a join over `by_file` —
and `find()` gives a file a key in `by_file` only once something cites into it — so
a file whose citations were ALL fixed was absent from the corpus at every number.
"Fixed every citation in this file" and "the ledger never mentioned this file"
were the same observation, and the entry sat there afterwards.

Measured on this tree before the fix: the ledger carried that entry, the file it
named had **zero** citations of any deleted doc, and `stale_baseline_entries`
answered `{}`.

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

**The instrument gap this is really about**, which is worth more than the four
rows: `tools/dangling_doc_refs.py` proves the corpus of citations can only
shrink, and nothing proves a surviving citation is still TRUE. A citation
survives its subject. If the ratchet is ever extended, the check to add is
"every `bugs/` path named in another `bugs/` document still exists" — which is
the `dangling` half and is already implemented — **plus** a per-file ratchet on
the count of citations *to a document that has been deleted*, which is what
would have caught these four at the moment of the delete rather than at the next
reader's convenience.

## What landed (2026-10-05)

**The stale half of the ratchet, which is a real defect and was hiding a real
entry on this tree.**

`stale_baseline_entries` is documented as existing to distinguish "an entry left
behind by a fix" from "one that is still needed", and it could not do that for the
case that matters most. It read `ledger_verdicts`, a join over `by_file` — and
`find()` only creates a `by_file` key once a file cites something — so **a file
whose citations were all fixed is absent from the corpus at every number**, and
its ledger entry was therefore invisible to every reader in the module: not the
ratchet (a ceiling above zero is never a gain), not `sanctioned` (the file is not
in the join), and not `stale_baseline_entries`. The join is now over the LEDGER,
looking each entry up with an observed count that is 0 when the file cites
nothing.

Measured, on this tree, before the change: the ledger carried
`bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md: 1`; that file has **zero**
citations of any deleted document; `stale_baseline_entries` answered `{}`. The
entry was raised on purpose by `--write-baseline` and then became unreachable,
which is the exact failure this document is about — one level down, in the tool
rather than in the prose.

`--ratchet` now **reports** stale entries, on the green path as well as the red
one, and does not fail on them. Reported-not-failed is the deliberate direction:
a gain is a citation somebody added and the fix is a prose rewrite, while a stale
entry is a citation somebody already fixed and the fix is deleting a line from
the ledger. A check that punishes a fix is a check that gets disabled.

**The stale entry is dropped**, which is the fix the tool then named:
`tools/dangling_refs_baseline.py` is one entry smaller, so the corpus count the
ledger implies is the corpus the tree has.

Pinned by `test_suite.py`'s `dangling refs: an entry for a file that cites
NOTHING is stale too, which the corpus join cannot see`, which asserts the
mechanism and not just the answer: that the file is absent from the synthetic
corpus **and** from `ledger_verdicts`, and is still reported stale. The
pre-existing `d.py` case (a file that still cites, under its ceiling) is kept as
the other half, so the two directions cannot be got wrong at once.

## What is still open

**The four rows in §"What is stale, and where" are still stale**, in three
documents held by other live claims (`python3 tools/control.py claims`):
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md`, `FORMAL_proof_coverage_census_
2026-10-03.md` (formal28-4) and `FORMAL_eighteen_examples_have_no_accepted_proof_
and_seven_are_declared.md`. The replacement text is the block quoted above; the
census row 5 also needs its `⊢ t32s (t8s n) = n` spelling corrected to
`⊢ t32s (t32u (t8s n)) = n`, and `FORMAL_floordiv_and_udivmod_are_red.md` (a
fifth bare citation, formal53-docs) cites the same deleted name.

**The bare class is still outside the ratchet**, and that is a decision rather
than a bug: 208-220 citations across ~86 files, no convention separating the
~20 historical "was X, deleted" sentences from a new one. `BARE_REF`'s comment
states the decision that would have to be made. This file is itself one of the
citations, on purpose — a document about stale citations that had none would be
a poor demonstration.

## Reproducing

```console
# §"What landed": the stale entry was visible and is now dropped. Before the
# fix the ledger named a file with zero citations and the tool said {}.
#
# NOT green on this tree, and the one failure is PRE-EXISTING on master in
# another worker's file (`FORMAL_the_interpolated_literal_reader_assumes_a_one_
# character_prefix.md` cites the deleted -b13 map with a `bugs/` prefix). It is
# named here rather than papered over because this file's whole subject is a
# citation that outlived its document.
$ python3 tools/dangling_doc_refs.py --ratchet
ratchet: 1 file(s) cite MORE deleted docs than tools/dangling_refs_baseline.py
allows:
  bugs/FORMAL_the_interpolated_literal_reader_assumes_a_one_character_prefix.md: 1

# the four rows, which are NOT this file's to fix — they are bare citations, and
# the bare class is outside the ratchet by the decision BARE_REF states.
$ python3 tools/dangling_doc_refs.py --by-file | grep narrow_typed
$ grep -rn FORMAL_arm64_a_narrow_typed_parameter bugs/ --include=*.md
```

FIVE hits now, not four: `bugs/FORMAL_floordiv_and_udivmod_are_red.md` carries a
sixth in the same bare spelling (formal53-docs). `bugs/OPEN_WORK.md` does not
list the document by name — its formal block is GENERATED
(`tools/formal_doc_index.py`), which is why deleting a doc updates it
automatically and why the `test_suite.py` check for a stale index went red when
this task deleted one.
