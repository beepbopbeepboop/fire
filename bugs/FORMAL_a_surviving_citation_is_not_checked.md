# Two documents that own no code still cite the deleted narrow-parameter doc

**Area:** documentation only. Found 2026-10-05 while deleting
`bugs/FORMAL_arm64_a_narrow_typed_parameter_makes_the_universal_contract_false.md`
with its fix.

**Status: OPEN. The `bugs/`-prefixed dangling count is back to a deliberate
floor of ONE (was zero), and that one is recorded here.**
`tools/dangling_doc_refs.py --ratchet --write-baseline` raised
`bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md: 0 → 1` so the gate stays
green, because that file is another worker's and the project rule is explicit
that the `bugs/`-prefixed corpus must not grow. The raise is the tool's own
sanctioned escape and the reason is this file; a worker who fixes the citation
should drop the entry rather than leave it.

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

## Reproducing

```console
$ python3 tools/dangling_doc_refs.py --ratchet     # green — the point
$ grep -rn FORMAL_arm64_a_narrow_typed_parameter bugs/ --include=*.md
```

Four hits, in the three files named above, plus `bugs/OPEN_WORK.md` if it lists
the document by name (check before editing: it is a triage index and its rows
move as claims are taken and released).
