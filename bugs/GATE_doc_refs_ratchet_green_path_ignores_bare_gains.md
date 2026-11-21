# GATE: `doc-refs --ratchet` exits 0 while the BARE half has a gain

**Job:** `doc-refs` (`python3 tools/dangling_doc_refs.py --ratchet`).
**Status:** open. Not the same bug as
`bugs/GATE_doc_refs_fallback_counts_its_own_ledger.md`: that one is
`candidates()` counting the ledger in the no-git fallback. This one is
`main()` computing the BARE verdict and then not consulting it when the
prefixed half is clean, so the two checks disagree about the same tree.

## What I ran

    python3 tools/dangling_doc_refs.py --ratchet
    # ratchet: no file gained a citation of a deleted doc
    # (540 `bugs/`-prefixed across 133 files, 92 bare across 48 files,
    #  all at or below their baseline)   exit 0

    python3 test_suite.py
    # FAIL dangling refs: the BARE class has a ledger of its own ...
    #   BARE_BASELINE has 47 entries and the corpus has 48 citing files;
    #   gains [('bugs/GATE_doc_refs_fallback_counts_its_own_ledger.md', 1, 0)]

    python3 - <<'EOF'
    import sys; sys.path.insert(0, 'tools')
    import dangling_doc_refs as d
    _have, by_doc, by_file = d.find()
    _bd, bf = d.bare_find()
    print(d.ratchet_verdict(by_file, bf)[1])
    EOF
    # [('bugs/GATE_doc_refs_fallback_counts_its_own_ledger.md', 1, 0)]

So the gain is real (`ratchet_verdict` returns it), the walk sees it
(`bare_find` returns 48 files against a 47-entry ledger), and `--ratchet`
still prints the green sentence and exits 0.

## Why

In `main()`'s `--ratchet` branch:

    regressions, bare_regressions = ratchet_verdict(by_file, bare_by_file)
    if not regressions:
        print('ratchet: no file gained a citation of a deleted doc ...')
        return 0

The green path tests only `regressions` (the `bugs/`-prefixed half). A
BARE gain with no prefixed gain falls through to `return 0` and never
reaches the block that would print it and `return 1`. The count in the
green sentence is printed from the same walk that found the gain, so the
output says "92 bare ... all at or below their baseline" while the ledger
check in `test_suite.py` reports one file above it.

This is the same failure class the comment above the call says the single
`ratchet_verdict` call exists to end — the prefixed and bare halves
"cannot disagree about what a gain is" — except they still can about
whether a gain is a failure. A citation campaign that reads `--ratchet`'s
exit code gets a green light for exactly the class that
`test_suite.py` was red on.

The immediate instance is a bug doc quoting a negative-control name from
the ledger's own output; the tool's convention for a deliberate mention is
a same-line comment or a `--write-baseline` ceiling, but either is only
visible once `--ratchet` actually reports the gain.

## Expected

`--ratchet` exits non-zero and names the BARE gain(s) whenever
`bare_regressions` is non-empty, exactly as it does when `regressions` is.

## Exact next step

In `tools/dangling_doc_refs.py::main()`, change the green-path condition
from `if not regressions:` to
`if not regressions and not bare_regressions:` (the print already reports
both halves and the failure block already prints `bare_regressions`).
Add a case to `test_dangling_doc_refs.py` that calls the `--ratchet` path
with a planted BARE-only gain and asserts exit 1 and a line naming the
file. As a separate decision, add the one ceiling the current corpus owes
with `python3 tools/dangling_doc_refs.py --write-baseline` (or reword the
quoted name), so `test_suite.py`'s BARE row is green again.
