# GATE: formal-doc-truth still red on the runtime ABI census figures

Found 2026-10-30 by the `formal-doc-truth` gate fix (branch
`work/fix-gate-formal-doc-truth`) while red on master at ebb934a7.

## What was fixed (on that branch)

Root cause of the non-census failures: commit 3f44ffd96 added
`mojo_cleanup_push_cattr` to `runtime/fire_runtime.h` (+6 lines). That
shifted the header citations in `doc/ABI.md` and left the new entry point
undocumented. Landed: `FORMAL.md` §1 KB figure 583 -> 589, `doc/ABI.md`
citations `606-608`/`579-604` -> `612-614`/`585-610`, a `mojo_cleanup_push_cattr`
bullet in the cleanup registry, and the entry in the test's `ABI_ENTRY_POINTS`.

## What remains (6 checks, `python3 test_formal_doc_truth.py`)

All six are runtime ABI census quotes that the live scan now measures higher:

- `FORMAL.md` §2.2 publishes `719` total (live `726`)
- `FORMAL.md` §2.2 publishes `297` word-shaped (live `300`)
- `FORMAL.md` §2.2 publishes `422` non-word (live `426`)
- `FORMAL.md` §2.2 says `fire_runtime.h` declares `616` (live `623`)
- `FORMAL.md` restates the non-word count `422` (live `426`)
- `FORMAL.md` §6 phase 2 publishes `297` word-shaped (live `300`)

The same stale quotes make `test_runtime_header_scan.py` (`rthdrscan`) red
across `FORMAL.md`, `formal/model.py`, `formal/build.py`,
`build_stdlib_dylib.py` and `bugs/formal/FORMAL_known_limits.md`. That lane is
claimed by `fix-gate-rthdrscan`, so these were not edited here.

## Next step

Re-pin the census quotes to the live scan in one pass, in the rthdrscan
lane (the `test_runtime_header_scan.py` census quotes are the source of
truth). Then `python3 test_formal_doc_truth.py` should report `FAIL=0`.
