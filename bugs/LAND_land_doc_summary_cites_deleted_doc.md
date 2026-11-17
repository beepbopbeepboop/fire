# LAND: a generated land doc cites a deleted doc, so `doc-refs` is red the moment it is filed

Status (2026-11-17): **open; not fixed here (the tool is the integrator's).**
Observed on master `b531a4f6a` while landing the cases-generator analyzer branch.

## What I ran

```
python3 tools/dangling_doc_refs.py --ratchet
```

## What I saw

```
ratchet: 1 file(s) cite MORE deleted docs than tools/dangling_refs_baseline.py allows:
  bugs/LAND-codegen-simd-and-array-values-erase-2.md: 1 (baseline 0) — <the simd part-2 doc, deleted>
```

A brand-new file (baseline 0) citing a deleted doc, so this is a GAIN and the
`doc-refs` job is red. The same doc does not exist any more: it was deleted by
the round that fixed it, before this land doc was filed.

## Root cause

`tools/integrate.py::land_doc` builds the new doc's `**Original work:**` line
from `t["summary"][:300]` verbatim. The task summary quotes the worker's
`TASK.md`, which says "Fix the bug in `bugs/<doc>.md` at its ROOT CAUSE", so the
generated doc carries a citation of the original bug doc. When that doc has
already been deleted (the common case — the branch being landed is the fix),
the new land doc starts at 1 dangling citation against a 0 ceiling.

This is not the worker's fault and not fixable by the worker whose doc it is:
that worker's own round will `git rm` the doc and take the citation away, but
until then every checkout is red in `doc-refs` (a `check`/`gate` job, no
`expect=` marker), and every other land round inherits the failure.

## Exact next step

In `land_doc`, sanitize the summary before writing it: replace any
`bugs/<...>.md` / `<STEM>.md` citation whose file does not exist in
`C.MAIN/bugs/` with the bare stem plus "(deleted)", or append " (deleted)" to
the `**Original work:**` line so `bare_find`'s deleted convention skips it
(the `bugs/`-prefixed class in `find()` has NO deleted skip, so a prefixed
`bugs/<name>.md` must be rewritten, not just annotated). Pin it in the
integrator's test that writes a land doc for a summary that names a deleted
doc, then assert `dangling_doc_refs --ratchet` stays green.

## Workaround used by this round

`bugs/LAND-codegen-nested-bracket-generic-call-4.md` had quoted the same kind
of status line, including the two cases-generator analyzer docs deleted by the
compiled-analyzer landing; that line now names the bugs instead of the paths,
which is the fix `--ratchet` asks for.
