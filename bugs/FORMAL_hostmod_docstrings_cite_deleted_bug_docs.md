# Host-module docstrings cite bug docs that do not exist

Found 2026-11-12 while verifying the merge of master into
work/fix-merge-bug-orchestration-formal-unlanded-task-s. The failing files are
byte-identical to master, so this is not caused by that merge.

## What ran

    python3 tools/memslot.py --gb 8 --label formal-link-acct -- python3 test_formal_link_accounting.py

Result: `365 passed, 1 failed, 366 checks`, exit 1. Failure:

    FAIL  every file a host module names exists: a docstring pointing at a test or a bug doc that is not there is a claim with nothing behind it: formal/hostmods/argparse.mojo:93 -> bugs/FORMAL_string_value_model.md; formal/hostmods/argparse.mojo:177 -> bugs/FORMAL_known_limits.md; formal/hostmods/argparse.mojo:2847 -> bugs/FORMAL_string_value_model.md; formal/hostmods/argparse.mojo:2893 -> bugs/FORMAL_known_limits.md; formal/hostmods/ast.mojo:42 -> bugs/FORMAL_known_limits.md; formal/hostmods/ctypes.mojo:279 -> bugs/FORMAL_string_value_model.md; formal/hostmods/hoststatus.mojo:9 -> bugs/FORMAL_no_exceptions.md; formal/hostmods/hoststatus.mojo:13 -> bugs/FORMAL_no_exceptions.md

## What was expected

Each docstring that names a bug doc either names an existing file or names the
bug by its symptom (the convention in doc/ and the dangling-refs ratchet).

## Next step

For each of the eight citations: if the bug is fixed, rewrite the docstring to
say what now holds (no doc path); if it is still open, file its doc (the
FORMAL_known_limits.md and FORMAL_string_value_model.md entries are the ones
the docstrings were meant to point at). Then run the same test. Also
`python3 tools/dangling_doc_refs.py --ratchet` must not regress.
