# TEST_formal_host_import_shapes_is_red_and_in_no_bucket: the dead-import ratchet has been red on both its rows, and no gate runs the file that checks it

**Area:** TEST (the harness — which tests a gate runs) / TOOLS
(`tools/formal_host_import_shapes.py`'s two instruments and the corpus they
read). Found 2026-10-05 on `work/formal73-docs`, while running the narrow tests
that cover a change to `formal/imports.py`'s tier classification —
`test_formal_host_import_shapes.py` calls `_imports._is_host_module` and
`host_module_tier`, so it is in the blast radius of that area even though it is
not in my claim. **Both failures are PRE-EXISTING and neither is caused by that
change**; the reason is recorded below so the next reader does not re-derive it
by reverting anything.

**The two failures are the same shape as
`TEST the formal doc truth census is in no bucket` — a census in no
bucket — which is why this is filed next to it rather than as a compiler bug.**

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- \
    python3 test_formal_host_import_shapes.py
F.F..F..s.......................................................
FAIL: test_a_row_that_wants_the_MODULE_reads_as_such
FAIL: test_the_whole_tree_has_one_dead_host_import_and_it_is_named
FAILED (failures=2, skipped=2)

$ grep -c formal_host_import_shapes tools/suite.py
0
$ python3 tools/suite.py --list | grep -c shapes        # the three hits are
3                                                            # other tests' prose
```

## What I saw

**Row 1 — a dead host import, and the file that owns it is
`tools/formal_doc_index.py`:**

```
AssertionError: {'fire_compiler.py': ['abc.abstractmethod'],
                  'tools/formal_doc_index.py': ['subprocess']}
             != {'fire_compiler.py': ['abc.abstractmethod']}
```

`tools/formal_doc_index.py:68` is `import subprocess` and the file mentions
`subprocess` **once** — `grep -c subprocess tools/formal_doc_index.py` prints
`1` — so it is an unused import. The ratchet says exactly what that costs:
"a dead host import blocks its file for exactly the reason an absent module
does, so each one is a file off the wall for nothing." `tools/formal_doc_index.py`
is the `bugs/OPEN_WORK.md` table's generator (`--write` / `--check`), so the
file is a real reader of this repository, not a scratch script.

**Row 2 — the `importlib.util` row is blocked on THREE names where the test
names two:**

```
AssertionError: ['importlib.util.find_spec', 'importlib.util.module_from_spec',
                 'importlib.util.spec_from_file_location']
             != ['importlib.util.module_from_spec',
                 'importlib.util.spec_from_file_location']
```

The test's own sentence states the row's rule — "the two that load a module by
PATH" — and `find_spec` is not one of them, so **the rule as written is what is
wrong, not the corpus.** `find_spec` is used by
`tools/formal_host_import_shapes.py` itself and by `formal/imports.py`, both of
which ask CPython *at build time on the host* whether a module exists, which is
the opposite of the capability the row is about: a freestanding image loading a
module by path. So the row's reason has to distinguish "resolves a name at build
time" from "loads a module at run time", and today it counts every name the row
has.

## Why this is PRE-EXISTING, and how that was established without a revert

`tools/dangling_doc_refs.py` aside, the reasoning is structural and does not
need a revert to be sound:

* **Row 1** names `tools/formal_doc_index.py` and `fire_compiler.py`. Neither is
  in any commit on this branch (`git diff master --stat` lists
  `formal/imports.py`, `formal/model.py`, `test_formal_imports.py`,
  `test_formal_link_accounting.py`, `test_formal_run.py`, the new
  `tools/formal_stdlib_reach.py` and two bug docs). `subprocess` is in
  `HOST_ADMITTED`, whose membership did not change, so the name was a host
  import before this branch exactly as it is now.
* **Row 2** is built from a sweep log's file list plus
  `tools/formal_host_import_shapes.py::uses_in` over those files. The only file
  this branch adds to the tree reads `importlib.util.find_spec` **and reads it**
  (`importlib.util.find_spec(name)` is called), and `uses_in` reports only names
  a file binds from the module and never READS — so a new reader cannot add a
  row, and `tools/formal_stdlib_reach.py` does not appear in the failure's
  `names` list.

## The next step, and it is two lines and one sentence

1. **Delete `import subprocess` from `tools/formal_doc_index.py:68`** — or use
   it, if the generator is supposed to shell out. One of the two is the whole
   fix, and the ratchet says which.
2. **State row 2's rule as what it is**: a name that makes the IMAGE load a
   module by path is the wall; a name that asks the HOST's `importlib` whether a
   module exists is a build-time lookup and is not. Either the row filters on the
   two path-loading names by name, or `uses_in` reports *why* a name blocks the
   file (run-time vs build-time), which is the better version because it is the
   question every consumer of the ranking actually has.
3. **Register the file.** `grep -c formal_host_import_shapes tools/suite.py` is
   `0`, so `formal-host-import-wall` (the registered job) and this file are two
   different instruments over the same area and only one of them is in a gate.
   `test_suite.py` checks both directions of "every registered test is in a
   bucket", not "every test file is registered", which is the gap this is.

## Why it is filed rather than fixed here

It is outside this worker's claims — no claim in `tools/control.py claims` names
`tools/formal_host_import_shapes.py` or `tools/formal_doc_index.py`, but the
area belongs to whoever holds the host-import instruments, and `formal68-docs`
holds `FORMAL_eleven_of_thirteen_host_import_rows_are_closure`, which is about
this area's rows. Two rows are enough to be worth a doc and small enough that
the fix is quick once someone owns it.