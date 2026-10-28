# FORMAL_host_import_shapes_is_red_for_a_stale_importlib_row_and_two_dead_subprocess_imports

**Area:** FORMAL — `test_formal_host_import_shapes.py` against the tree it walks,
and the tool it checks (`tools/formal_host_import_shapes.py`). **Filed, NOT
fixed**: both causes are the host-import-wall lane's
(`bugs/FORMAL_the_host_import_wall_is_at_its_honest_floor.md`, which already
records the `find_spec` half at its §284), not this worker's eight documents, and
the fix is a decision about somebody else's test expectations.

## What I ran

    python3 tools/memslot.py --gb 8 --label his -- python3 test_formal_host_import_shapes.py

## What I saw

    Ran 26 tests in 6.689s
    FAILED (failures=2, skipped=2)

Two failures, both on `TestAgainstTheRealCorpus`:

1. `test_a_row_that_wants_the_MODULE_reads_as_such` — the `importlib.util` row
   now names **three** symbols and the test asserts **two**:

       got      ['importlib.util.find_spec',
                 'importlib.util.module_from_spec',
                 'importlib.util.spec_from_file_location']
       expected ['importlib.util.module_from_spec',
                 'importlib.util.spec_from_file_location']

   `find_spec` is the third, and it is already in the table:
   `FORMAL_the_host_import_wall_is_at_its_honest_floor.md:284` names
   `spec_from_file_location`/`find_spec` together for this row ("the same
   host-process capability as `importlib` above, under a name the corpus grew
   into"). So it is the hard-coded expectation in the test, not the tool, that is
   behind.

2. `test_the_whole_tree_has_one_dead_host_import_and_it_is_named` — the tree now
   has **three** unread host imports and the test asserts **one**:

       ['fire_compiler.py':          ['abc.abstractmethod'],
        'tools/formal_metamorph.py': ['subprocess'],
        'tools/formal_doc_index.py': ['subprocess']]

   `formal_metamorph.py:148` carries
   `import subprocess  # noqa: F401  — re-exported for callers that shim this
   module`, and no file in the tree reads `formal_metamorph.subprocess` or
   `formal_doc_index.subprocess` (measured: `grep -rn "metamorph.subprocess\|
   doc_index.subprocess" --include=*.py .` is empty; a `.`-attribute read count
   for each file is 0). `dead_host_imports` reads a host import as dead when its
   bound name is never LOADED (`tools/formal_host_import_shapes.py::_dead_in`),
   and a re-export is exactly that, so both are reported.

The `fire_compiler.py` row is the one the test wants and is unchanged. Neither
failure is caused by this worker's commit: both are properties of the tree
`master` and reproduce on a clean checkout.

## The exact next step, per cause

1. **The `importlib.util` row:** update the expected list at
   `test_formal_host_import_shapes.py:349` to the three names the tool now
   reports, and say in the case's docstring that `find_spec` is the third (the
   same capability — loading a module by PATH — under the name the corpus grew
   into, which the wall doc's §284 already records). Re-run the one test.

2. **The two `subprocess` imports:** decide which side is wrong.
   `tools/formal_doc_index.py:68` has no stated reason and is plainly dead —
   deleting it is the whole fix and the file uses `subprocess` nowhere.
   `tools/formal_metamorph.py:148` says it is re-exported for a shim, and no
   caller in the tree reads it, so either (a) delete it too and update whatever
   the shim was going to be, or (b) if the re-export is intended, make
   `_dead_in` treat a `# noqa: F401` (or a new explicit marker) as "read", which
   changes the tool's contract and owes a case in the same test file. Option (a)
   is the smaller change and is what the test's own message asks for ("Delete the
   import, or say here why it stays").

Both are Red in `proofs` only (`formal-host-import-shapes` is not in `gate`),
which is why they have gone unobserved.
