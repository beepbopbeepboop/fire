# GATE: `doc-refs --ratchet` reports GREEN when only the BARE class gained a citation

**Job:** `doc-refs` (`python3 tools/dangling_doc_refs.py --ratchet`).
**Status:** open. Not the same bug as
`GATE_doc_refs_fallback_counts_its_own_ledger.md` (a `git ls-files` fallback
that counts the ledger itself, in `candidates()`); this one is the verdict in
`main()`, and it makes the bare half of the ratchet unenforceable.

## What I ran

On this branch, a new bug doc's line 4 cited a deleted doc by bare stem (the
float augmented-assignment doc, with no `bugs/` prefix). Running the job took
the green path:

    python3 tools/dangling_doc_refs.py --ratchet

Exit 0, ending

    ratchet: no file gained a citation of a deleted doc (540 `bugs/`-prefixed
    across 133 files, 93 bare across 49 files, all at or below their baseline)

That sentence is wrong about the bare class: it grew from 92 across 48 files to
93 across 49, and the new file's only citation is that bare one. The prefixed
class did not move, which is why the run is green. (The citation was reworded
afterwards, so the repro below does not depend on it.)

The defect is reproducible with a fabricated corpus, no file edits needed:

```python
>>> import sys; sys.path.insert(0, 'tools')
>>> import dangling_doc_refs as D
>>> D.ratchet_verdict({}, {'bugs/TMP_x': [('gone.md', 1)]}, {}, {})
([], [('bugs/TMP_x', 1, 0)])
```

`ratchet_verdict` returns a non-empty bare tuple, and `main()`'s green
condition still ignores it (the real run above is that same state).

## Root cause

`main()`'s `--ratchet` branch computes both halves through `ratchet_verdict`,
then tests only the prefixed one:

    if not regressions:
        print(f'ratchet: no file gained a citation of a deleted doc ...')
        return 0
    print(f'ratchet: {len(regressions) + len(bare_regressions)} file(s) ...')

A bare-only gain is printed as green and exits 0; the failure reporter below
(the one that names `BARE baseline`) is unreachable for that case. This is the
same class of defect the tool's own `ratchet_verdict` docstring says was fixed
by judging both walks in one function — the join is right, the caller's
condition was not updated with it.

## Exact next step

In `tools/dangling_doc_refs.py::main()`, make the green path require both:
`if not regressions and not bare_regressions:` (and keep the message's counts
consistent with that condition). Add a case to `test_dangling_doc_refs.py`
that calls `ratchet_verdict` with an empty prefixed corpus, a one-entry
`bare_by_file` whose key is not in `BARE_BASELINE`, and an empty
`bare_baseline`, and asserts the bare tuple is non-empty and that `main()`'s
decision (or a helper it is factored into) is non-zero. Then re-run
`python3 test_dangling_doc_refs.py` and the planted-corpus case in
`tools/suite.py`'s `suite-self-test`.

One thing fixing this will surface: the tree ALREADY carries a bare citation
this bug masks (which is why the message says "all at or below their
baseline" while one file is above its 0). It is in another doc-refs bug doc
that quotes `tools/dangling_refs_baseline.py`'s own key list, so that file's
`BARE_BASELINE` reading is 1 against a ceiling of 0. Turning the check on
means dealing with that row too — reword the quote so it does not spell a
deleted doc's name, or raise the ceiling on purpose with `--write-baseline`
after reading the diff.

Reported, not fixed, because `tools/dangling_doc_refs.py` is another worker's
claimed area (`bug:GATE_doc_refs_fallback_counts_its_own_ledger`).
