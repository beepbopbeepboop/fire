# SUITE: doc-refs ratchet red — two pre-existing citation gains on master

**Status (2026-11-13):** open. Filed from the work/bug-interp-list-ctor-wraps-
its-iterable lane, which ran the required `python3 tools/dangling_doc_refs.py
--ratchet` right after it git rm'd the INTERP_list_ctor_wraps_its_iterable.md
doc (its own deletion is ratchet-clean: no file gained a citation of that
deleted doc) and found the job red for two reasons that lane did not cause.
(The names below are spelled the way the ratchet itself prints them, without
a `bugs/` prefix, on purpose: a `bugs/<deleted-doc>.md` spelling anywhere in
a tracked file is itself a regression this doc exists to report.)

## What was run

    python3 tools/dangling_doc_refs.py --ratchet

## What was seen (exit 1; the trailing clause on each row is an annotation
## added here, not part of the output)

    ratchet: 2 file(s) cite MORE deleted docs than tools/dangling_refs_baseline.py allows:
      bugs/GATE_selfhost_closure_cannot_compile.md: 1 (baseline 0) — mid/CODEGEN_selfhost_sig_table_parse_module_recover.md, deleted from the tree
      bugs/hard/README.md: 1 (BARE baseline 0) — DIAGNOSTICS_align_decorator.md, deleted from the tree

Both regressions are PRE-EXISTING on master, verified against the branch base
(neither file was touched by the lane that filed this):

- The cited line at `bugs/GATE_selfhost_closure_cannot_compile.md:118` names
  mid/CODEGEN_selfhost_sig_table_parse_module_recover.md, a doc deleted from
  the tree, so the gain landed with that doc, after the doc-refs `expect=`
  marker was dropped (see the registration's comment in `tools/suite.py`,
  2026-11-09 campaign note).
- The line at `bugs/hard/README.md:18` names the deleted
  DIAGNOSTICS_align_decorator.md doc bare; it resolves to no `.md` anywhere
  in the tree, and the line is in `master:bugs/hard/README.md` too.

`test_suite.py`'s `doc-refs` job runs exactly this command with no `expect=`
marker, so `check` (and therefore the integrator's gate) is red on these two
lines today, on master, for no lane that is being gated.

## What was expected

`ratchet: no file gained a citation of a deleted doc` — the marker was dropped
only after the campaign claimed the corpus was at its baselines, so a gain on
master's tip is a regression the marker's own anti-rot exists to report.

## Exact next step

One prose rewrite per line, in the file that owns the citation (the fix the
ratchet's own failure message names):

1. `bugs/GATE_selfhost_closure_cannot_compile.md:118` — rewrite the citation
   to name the BUG (its symptom, or the commit that fixed
   CODEGEN_selfhost_sig_table_parse_module_recover) instead of the path.
   The bare walk skips a line that says the doc was deleted (its
   `deleted|git rm|...` convention); the prefixed walk counts no spelling of
   a `bugs/` path at all, which is the cleaner fix here. This doc sits in
   the `fix-selfhost-gate` lane's claimed area
   (`bug:GATE_selfhost_closure_cannot_compile`), so that lane is the natural
   owner of the edit.
2. `bugs/hard/README.md:18` — the deleted DIAGNOSTICS_align_decorator.md
   row: rewrite the cell to name the bug or the commit, or drop the row if
   the doc is the whole entry (the README is the shared triage index; no
   lane claimed it).

Then `python3 tools/dangling_doc_refs.py --ratchet` must print no
regressions (the stale-entry report is reporting-only, the opposite
direction, and never fails). The alternate for a citation that is
DELIBERATE is the ratchet's own escape hatch: `--write-baseline` after
reading the diff. Not recommended here: both lines read as live pointers to
documents that are not there.
