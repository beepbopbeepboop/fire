# SUITE: `test_conditional_conformance_synthesis_diagnostic.py` is run by no job

**Status (2026-11-13):** open. Found while finishing
`bug:SUITE_trait_requirement_evidence_unregistered` (same failure shape, a
different file). This file is not in my claim; it is filed here rather than
fixed because the trait-conformance lane that produced it is still running
(`bug:DIAGNOSTICS_trait_conformance-part5`, `-part6` are claimed) and its
documents tell their workers NOT to register their test files.

## Repro

    python3 test_suite.py

ends

    Results: 375 passed, 3 failed
      - the estate: every test file is run by something, or says why not:
        not run by any registered spec, not in UNREGISTERED, and in no
        declared family: test_conditional_conformance_synthesis_diagnostic.py

The other two rows in that run are `formal-doc-truth` / `rthdrscan`
(`bugs/gate-formal-doc-truth.md`, `bugs/gate-rthdrscan.md`), not this one.

## What was measured

The file arrived in `65cee30d4` ("diagnostics: reject unsynthesizable copy/move
under conditional conformance (part 4)"), which added it and deleted the
part-4 trait-conformance document in the same commit, but registered nothing.
It runs green on its own:

    python3 test_conditional_conformance_synthesis_diagnostic.py
    # ... all tests passed

It is a `compile_to_gimple`-only, no-build suite like the part-2 one in
`bug:SUITE_trait_requirement_evidence_unregistered`: cheap, so `expect=` /
`disabled=` are both wrong answers.

## Root cause: two instructions that contradict each other

The trait-conformance docs say, in their `## Acceptance check`:

    Add `test_trait_comptime_member_conformance_diagnostic.py` (next to the
    other `test_*_diagnostic.py` files; do NOT register it in `tools/suite.py`).

That instruction predates (or ignores) `test_suite.py`'s estate check, which
requires every `test_*.py` on disk to be named by a spec, listed in
`UNREGISTERED`, or matched by a declared family. Each new
`test_*_diagnostic.py` this lane lands therefore turns `suite-self-test` red
the moment it merges, and the parts 5/6/7 documents each promise another one.

## Exact next step

Pick one, for the whole family and not for this one file:

1. **Register them** (the part-2 precedent): a `test(...)` registration each,
   `mem='tiny'`, in the `check` bucket beside `where-clause-call-site-diagnostic`
   (they are cheap in-process diagnostics), and change the `## Acceptance check`
   sentence in `bugs/mid/DIAGNOSTICS_trait_conformance-part{3,5,6,7}.md` from
   "do NOT register it" to naming the registration; or
2. **Excuse them with a reason** in `test_suite.py`'s `UNREGISTERED` (for the
   part already landed), and change those documents to say which entry to add.
   This is the weaker answer: these suites are cheap and pin diagnostics that
   would otherwise not run.

Until one of those lands, `suite-self-test` stays red on every gate, which is
the same coverage hole the estate check exists to name.
