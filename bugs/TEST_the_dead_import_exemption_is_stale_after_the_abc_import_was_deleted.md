# TEST: `test_formal_sweep_truth.py`'s `abc` dead-import exemption is stale, so the test is RED on master

**Area:** `test_formal_sweep_truth.py::TestHostImportRowsAreNotDeadImports::
test_a_named_dead_import_is_still_named` and its
`_ROWS_WITH_A_NAMED_DEAD_IMPORT = ("abc",)` (line 749). **Found 2026-10-13 on
`work/formal400-docs` while running the narrow suites for an unrelated FORMAL
fix; PRE-EXISTING on master** (this branch touches
`test_formal_call_proof_gen.py` and one bug doc, neither of which names `abc`).

## What I ran

    $ export PATH=/opt/homebrew/bin:$PATH
    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py
    Ran 140 tests in 55.601s
    FAILED (failures=1)

## What I saw

    FAIL: test_a_named_dead_import_is_still_named
          (__main__.TestHostImportRowsAreNotDeadImports) (module='abc')
    AssertionError: 'abc' not found in {...} : `abc` no longer has a file that
    imports it at all, so it is not a dead-import row and does not need an
    exemption; drop it from _ROWS_WITH_A_NAMED_DEAD_IMPORT. The rows the census
    does have are ['asyncio', 'atexit', 'builtins', 'collections', 'copy',
    'datetime', 'difflib', 'fractions', 'functools', 'importlib', 'inspect',
    'pickle', 'resource', 'socket', 'sysconfig', 'types', 'unittest', 'uuid',
    'warnings']

## What I expected

The test's own contract: every name in `_ROWS_WITH_A_NAMED_DEAD_IMPORT` is a
CLAIM ("this name is a dead-import row, and here is why"), and the row must still
have files and NO readers.  `abc` has neither now.

## The cause, and it is one commit

`73e03459` ("docs: delete the tree's dead host imports, and the ratchet is now
clean", 2026-10-08) deleted `fire_compiler.py`'s
`from abc import abstractmethod` — the tree's ONLY importer of `abc`
(`grep -rn "import abc\b" --include=*.py .` now finds only a comment in
`gimple_codegen.py`).  That commit updated `test_formal_host_import_shapes.py`
(whose `test_the_whole_tree_has_no_dead_host_import` now asserts `{}`), but not
`test_formal_sweep_truth.py`, whose exemption `_ROWS_WITH_A_NAMED_DEAD_IMPORT`
was last touched by `76143aaa` ("The host-import row list is derived from the
tiers, not hand-written").  So the exemption outlived the import it excused, and
its guard test has been red since — invisible whenever `lib/ProofLib.olean` is
absent only if a run stops at an earlier red, which is not the case here
(measured with the library absent: 140 tests, this one failure).

The comment block above the tuple (lines 742–749) is stale in a second way: it
cites `test_formal_host_import_shapes.py::test_the_whole_tree_has_one_dead_host_
import_and_it_is_named`, which `73e03459` renamed to
`test_the_whole_tree_has_no_dead_host_import`.

## The exact next step

In `test_formal_sweep_truth.py`:

1. `_ROWS_WITH_A_NAMED_DEAD_IMPORT = ()` — the tuple is now empty, which is the
   state `test_formal_host_import_shapes.py` already asserts for the tree.
2. Rewrite the comment block above it: it explains an `abc` exemption that no
   longer exists, and it cites the renamed
   `test_the_whole_tree_has_no_dead_host_import`.
3. Re-run and confirm the class is green.  `test_a_named_dead_import_is_still_
   named` iterates the (now empty) tuple, so it asserts nothing — the class's
   other rows (`test_the_other_rows_still_have_users`, and the derived
   `_host_row_census` row above it) are what keep the derivation honest, and
   `tools/formal_host_import_shapes.py --dead` (the mode
   `FORMAL_a_call_result_field_access_has_no_representation.md` §3 names)
   returns `{}`, so the empty tuple is the measured state.

    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py
    # expect: the TestHostImportRowsAreNotDeadImports failure gone (with
    # lib/ProofLib.olean absent, the AXIOM-closure class skips; with it
    # present, that class's own pre-existing staleness is a separate doc)

This is outside `work/formal400-docs`'s six claimed docs (its subject is the
host-import wall, `FORMAL_a_call_result_field_access_has_no_representation.md`),
which is why it is filed rather than fixed here.
