# DOCS_formal16_2_deleted_the_bit_test_doc_under_a_survey_another_worker_owns

**Area:** DOCS — `tools/dangling_doc_refs.py`'s census, and one merge's claim
boundary.
**Status: MERGED, the dangling citation is still there, and it is one line wide
for whoever holds the file.** Found on `work/merge-formal18` while merging
`work/formal16-2`; filed rather than fixed because the file is another worker's
claim.

## What happened

`work/formal16-2` fixed the bit-test gap — an `if` on a bit test
(`if n & 8:`) now lowers, emits a `TBZ`, and is provable — and deleted
`“An `if` whose condition is a BIT TEST cannot be PROVED”` with its fix, which is
what this project's rule says to do with a fixed bug's doc.

Two files it wrote in the preceding commits cited that doc, and its own last
commit (`b741206f`, "name the symptom instead of the deleted bit-test doc, so no
citation dangles") fixed those two and said plainly:

> One citation is left and is NOT mine to fix:
> `bugs/FORMAL_arm64_instruction_coverage.md` lines 16 and 156 still cite the
> deleted doc. That file is `work/formal16-3`'s claim; … editing another
> worker's claim from here is how two branches end up with the same line.
> Reported instead.

So the branch knew, said so, and left it. That judgement was right — and the
merge is where the leftover becomes visible, so this is the record of it.

## What I measured, on the merged tree

```console
$ python3 tools/dangling_doc_refs.py | head -1
659 citations of 262 bugs/ docs that are not there, across 210 files

$ grep -rn FORMAL_arm64_bit_test_branch_is_not_provable --include='*.md' .
./bugs/FORMAL_arm64_instruction_coverage.md:16
./bugs/FORMAL_arm64_instruction_coverage.md:156
```

Before the merge (`master` = 86d60026) the same census reads **658 citations of
261 docs across 209 files**, and the delta between the two lists is exactly
this one document. So the merge adds one dangling citation and nothing else
removes one — the other five docs `formal16-2` deleted were cited nowhere.

The two sites, verbatim:

* **line 16** — the header's list of sibling bug docs: "…`FORMAL_arm64_known_
  proof_gaps.md` for the three unproved examples, and
  `FORMAL_arm64_bit_test_branch_is_not_provable.md` for the one gap the
  TBZ/TBNZ wiring left behind."
* **line 156** — the survey's "what is NOT done" paragraph, which says the bit
  test "compiles, runs, and answers CPython, and cannot be *proved*" and points
  at the doc for "the measurement, the site, and the next step".

## Why not fixed here

`FORMAL_arm64_instruction_coverage` is worker `formal18-2`'s claim (checked with
`tools/control.py claims` during this merge). It is a SURVEY, and the fix is not
a mechanical find-and-replace: line 156's whole paragraph is now false, because
the thing it reports as unproved is proved. It needs the successor's facts —
which program, which `work_step_*` lemma, which example file — and a survey that
repeats a stale "cannot be proved" is worse than one that cites a missing file,
because a reader stops checking.

## Exact next step

In `bugs/FORMAL_arm64_instruction_coverage.md`, on a branch holding that claim:

1. Delete the two citations and rewrite line 156's paragraph to say the bit-test
   case is now PROVED and where — `formal/examples/bittest.mojo` is the example
   file `formal16-2` added, and `test_formal_call_proof_gen.py`'s
   `TestBitTestBranches` is the suite that pins it, so those are the two things
   to name rather than a symptom.
2. Re-run `python3 tools/dangling_doc_refs.py` and confirm the count returns to
   **659 citations of 262 docs across 210 files** — not the 658/261/209 of
   pre-merge `master`, because this doc is itself one of the 659: it names the
   tool that measures the thing it reports, which is what
   `bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md` does and the
   reason its own citation is in its census.
3. If the survey's own numbers moved (it quotes "covered" instruction counts),
   re-take them rather than editing the figure: `tools/arm64_insn_audit.py` is
   the instrument the file names for exactly that.

Nothing else is outstanding — the merge that carried the fix is
`work/merge-formal18`'s first commit, and it is committed and green on every
test this merge touches.