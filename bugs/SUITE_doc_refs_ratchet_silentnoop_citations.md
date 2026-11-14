# GATE doc-refs: the ratchet is red on master from a deleted container-kind doc

**Job:** `doc-refs` (`python3 tools/dangling_doc_refs.py --ratchet`, registered
in `check`). Found 2026-11-14 while retiring the `stdlib-syntax` gate doc.

## What I ran

From `/Users/mrs/net/chatgpt/claude/work-7228` at master `d2bc1dd5d`:

    python3 tools/dangling_doc_refs.py --ratchet

## What I saw

    ratchet: 1 file(s) cite MORE deleted docs than tools/dangling_refs_baseline.py allows:
      bugs/SUITE_silentnoop-part1-findings.md: 2 (baseline 0)

The two citations are lines 11 and 59 of that findings doc. They point at the
container-kind defect doc that commit `e4a2cc2ed` ("codegen: specialize
literal-kind mixed params including None/comprehensions") deleted without
running the ratchet. This is independent of the `stdlib-syntax` doc deletion:
the same failure reproduces with that deletion reverted, and the commit that
deletes it adds no citation.

## What I expected

`--ratchet` exits 0: no file gains a citation of a deleted doc.

## Why I did not fix it

The citation lives beside the container-kind work, which another lane claims
(`bug:CODEGEN_param_container_kind_coerce_blocks_selfhost`), so editing it here
would cross that claim.

## Exact next step

In `bugs/SUITE_silentnoop-part1-findings.md`, replace both citations with the
bug the container-kind doc described — the `silentnoop` job /
`test_silent_noop_iter.py` build-error classification (symptom) or the fixing
commit — then rerun `python3 tools/dangling_doc_refs.py --ratchet` and confirm
it exits 0. Commit that with the citation fix.
