# GATE: `doc-refs --ratchet` goes red when `git ls-files` cannot answer

**Job:** `doc-refs` (`python3 tools/dangling_doc_refs.py --ratchet`).
**Status:** open. Not the same bug as the retired `gate-doc-refs` filing; that
one was a real citation gain in `tools/test_integrate_probe_loop.py`, fixed by
its ledger entry (3783b2cf1). This is the tool disagreeing with itself about
which files are candidates.

## What I ran

At HEAD (which is green in the worktree), export the commit somewhere with no
`.git` and run the same job there:

    rm -rf .tmp/headmove && mkdir -p .tmp/headmove
    git archive HEAD | tar -x -C .tmp/headmove
    cd .tmp/headmove && python3 tools/dangling_doc_refs.py --ratchet

## What I saw

Exit 1, with two gains that are not citations:

    warning: `git ls-files` exited 0; walking the filesystem instead, so this run also sees untracked files
    ratchet: 2 file(s) cite MORE deleted docs than tools/dangling_refs_baseline.py allows:
      tools/dangling_refs_baseline.py: 1 (baseline 0) — LAND-fix-replan-gate-red-recover-land-2026-11-02-part5-p.md
      tools/dangling_refs_baseline.py: 1 (BARE baseline 0) — NEVER_WRITTEN.md

The run in a real worktree is exit 0 with the same commit. The two extra rows
are the ledger's own keys and negative-control names being counted as
citations of deleted docs.

## Why

`candidates()` has two paths. The `git ls-files` path filters out `SELF_PATH`
(the ledger) and derived directories. The filesystem fallback — taken whenever
`git ls-files` exits non-zero **or returns empty stdout** — filters derived
directories but does not filter `SELF_PATH`, so `tools/dangling_refs_baseline.py`
is scanned like any other `.py`. Its whole content is the names of deleted docs
still cited elsewhere, so the fallback reports the ledger as a citer of each of
them. `--write-baseline` in that state would also try to record a ceiling for
the ledger, which `BASELINE_PATH`'s docstring says cannot mean anything.

This is the same failure class the tool's own comments call out: two answers for
two checkouts of one commit. Here it is two answers for a checkout and an
export of that same commit, and the export is a false red.

## Expected

The fallback should apply the `SELF_PATH` exclusion, so the answer is the
commit's citations plus this tree's untracked scaffolding, never the ledger
itself.

## Exact next step

In `tools/dangling_doc_refs.py::candidates()`, apply `rel != SELF_PATH` in the
fallback loop as the `git ls-files` path already does (and keep the warning).
Add a case to `test_dangling_doc_refs.py` that forces the fallback (mock
`subprocess.run` to return an empty or failing `git ls-files`) and asserts
`tools/dangling_refs_baseline.py` is not in `candidates()` while an ordinary
tracked `.py` is. Verify with `python3 test_dangling_doc_refs.py` and
`python3 tools/dangling_doc_refs.py --ratchet` in both the worktree and the
`.tmp` export above.
