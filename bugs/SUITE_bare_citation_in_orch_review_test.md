# `test_suite.py` self-test: `tools/test_orch_review.py` gained a bare doc citation

**Found by:** the `bug:gate-rthdrscan` lane (2026-11-14), running
`python3 test_suite.py` — a file this lane touched, so it ran the whole file.
**Not caused by that lane:** `tools/test_orch_review.py` and
`tools/dangling_refs_baseline.py` are unmodified on this branch.

## What I ran

    python3 tools/memslot.py --gb 8 --label testsuite -- python3 test_suite.py
    python3 tools/dangling_doc_refs.py --ratchet

## What I saw

    - dangling refs: the BARE class has a ledger of its own, and it is green on
      arrival — a citation spelled without `bugs/` is judged too:
      BARE_BASELINE has 46 entries and the corpus has 47 citing files;
      gains [('tools/test_orch_review.py', 1, 0)]

The citing lines are `tools/test_orch_review.py:43` and `:88-89`, which use
synthetic example doc names as single string literals (spelled here with the
extension split off so this doc does not itself become a citation of them):

    doc = os.path.join(d, "main", "bugs", "ORCH_REVIEW_bug-codegen-foo" + ".md")
    orphan = os.path.join(bugs, "ORCH_REVIEW_orphan" + ".md")
    held = os.path.join(bugs, "ORCH_REVIEW_bug-held" + ".md")

`dangling_doc_refs.BARE_REF` matches `[A-Z][A-Za-z0-9_]{4,}\.md` wherever it
appears in a tracked `.md`/`.py`, so each is counted as a citation of a
document that is nowhere in the tree. The baseline has no entry for the file,
so a file that has never had a real citation is reported as a regression. The
same check is red on master's tree (`git show d3ec70ee7:tools/dangling_refs_baseline.py
| grep -c test_orch_review` is `0` while the strings are present).

## What I expected

`--ratchet` green on arrival, as it is for every other file in `BARE_BASELINE`.

## Exact next step

These are fixture names, not citations, so do not bank a ceiling for two
documents that never existed. Build each path so the `.md` is not part of one
contiguous token, the way `test_gate_rthdrscan.py` builds the doc path it
checks for the existence of:

    "ORCH_REVIEW_bug-codegen-foo" + ".md"

(Same for `ORCH_REVIEW_orphan` and `ORCH_REVIEW_bug-held`.) The assertions
compare whole paths, so the built string is unchanged at run time. Re-run
`python3 tools/dangling_doc_refs.py --ratchet` and `python3 test_suite.py`.
