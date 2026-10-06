# DOCS_formal16_2_deleted_the_bit_test_doc_under_a_survey_another_worker_owns

**Area:** DOCS — `tools/dangling_doc_refs.py`'s census, and one merge's claim
boundary.
**Status: the citation is STILL THERE (`bugs/FORMAL_arm64_instruction_coverage.md:16`
and `:156`, `formal25-2`'s live claim, not edited from here), and it is now
INVISIBLE no longer: `tools/dangling_doc_refs.py` grew a BARE-citation census on
2026-10-04 which finds it, because the reason it survived two merges is that
neither site spells the `bugs/` prefix the tool's regex requires. Measured:
289 bare citations of 147 names that are nowhere in the tree, across 109 files,
and `bugs/FORMAL_arm64_instruction_coverage.md:16` is one of them.** Found on
`work/merge-formal18` while merging `work/formal16-2`; filed rather than fixed
because the file is another worker's claim.

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

## The reason it survived the ratchet (measured, 2026-10-04)

`tools/dangling_doc_refs.py`'s `REF` requires the `bugs/` prefix:

```python
REF = re.compile(r'bugs/((?:hard/|consolidated/)?[A-Za-z0-9_][A-Za-z0-9_./+-]*'
                 r'\.md)')
```

Both sites in the survey write the doc's STEM with no directory in front of it
("`FORMAL_arm64_bit_test_branch_is_not_provable.md` for the one gap the TBZ/TBNZ
wiring left behind"), so `--ratchet` — the one check that is supposed to go red
when a doc is deleted with thirty citations of it — never saw them, and the
census's own count was 6 citations in 1 file both before and after the deletion
that created this one.

`BARE_REF` and `bare_find` are the fix, and they resolve a bare stem by
EXISTENCE rather than by spelling: it counts as a citation only when
`bugs/<stem>.md` is absent AND no `.md` of that basename exists anywhere in the
tree — which is what keeps `doc/ELABORATION.md` and
`doc/MODULE_CACHE_DESIGN.md`, cited bare by four files each, out of the report.
A line that already says the doc was deleted is skipped, because that is the
convention `bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md` §2
established and a sentence *about* a deleted doc is not a sentence that *needs*
one.

It is reported and deliberately NOT in the ratchet: a bare citation has no
convention that separates the ~20 historical "was X, deleted" sentences from a
new one, and this tree is worked from dozens of worktrees at once, so a ledger
for it would move a number any branch editing the same prose moves. Making it
visible is what pays; a verdict on it is a decision for whoever owns the tool.

## Exact next step

In `bugs/FORMAL_arm64_instruction_coverage.md`, on a branch holding that claim
(`formal25-2`):

1. Delete the two citations and rewrite line 156's paragraph to say the bit-test
   case is now PROVED and where — `formal/examples/bittest.mojo` is the example
   file `formal16-2` added, and `test_formal_call_proof_gen.py`'s
   `TestBitTestBranches` is the suite that pins it, so those are the two things
   to name rather than a symptom.
2. Re-run `python3 tools/dangling_doc_refs.py` and confirm the citation is gone
   from BOTH counts — the `bugs/`-prefixed one and the bare one, which is where
   this one actually lives. The doc's original 659/262/210 figures are from
   2026-10-03 and the census has moved a long way since (6 citations in 1 file
   today, plus 289 bare ones); what to check is that
   `FORMAL_arm64_bit_test_branch_is_not_provable.md` appears in NEITHER list.
3. If the survey's own numbers moved (it quotes "covered" instruction counts),
   re-take them rather than editing the figure: `tools/arm64_insn_audit.py` is
   the instrument the file names for exactly that.

Nothing else is outstanding — the merge that carried the fix is
`work/merge-formal18`'s first commit, and it is committed and green on every
test this merge touches.