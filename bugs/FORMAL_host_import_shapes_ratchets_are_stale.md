# FORMAL_host_import_shapes_ratchets_are_stale: two `test_formal_host_import_shapes.py` rows are red on `master`, and each is a fixture a real change outran

**Status: OPEN, measured, not fixed.** Found 2026-10-13 on `work/formal368-docs`
while checking the blast radius of the tiers added under
`FORMAL_stdlib_module_names_are_not_classified.md` — every host-import
instrument has to be re-run when a name changes tier. **Both failures are
PRE-EXISTING on `master` at `1a08f414`**: measured by reverse-applying all of
this branch's diff and re-running the file, 2 failures before and 2 after,
identical messages:

```console
$ git diff > .tmp/d.patch && git apply -R .tmp/d.patch
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_host_import_shapes.py
Ran 26 tests in 7.4s
FAILED (failures=2, skipped=2)
$ git apply .tmp/d.patch
```

`tools/formal_host_import_shapes.py` and its test file are in no live claim, so
this is filed rather than edited.

## 1. `TestAgainstTheRealCorpus::test_a_row_that_wants_the_MODULE_reads_as_such`
## — the `importlib.util` row grew a third name, and it is `find_spec`

Expected (the fixture at `test_formal_host_import_shapes.py:349`):

```
["importlib.util.module_from_spec", "importlib.util.spec_from_file_location"]
```

Found:

```
['importlib.util.find_spec',
 'importlib.util.module_from_spec',
 'importlib.util.spec_from_file_location']
```

**The reader is right and the fixture is stale.** The row's `names` is the set
of names of the module that the corpus's LIVE files spell, and
`test_formal_imports.py::test_the_find_spec_decided_names_are_unreachable`
(added 2026-10-07 with the five `find_spec`-decided names) spells
`importlib.util.find_spec`. So `test_formal_imports.py` is a live file in that
row and `find_spec` is a name it wants — the third of the same
load-a-module-by-path family the docstring names.

**Next step:** extend the expected list to the three names and correct the
docstring, which says the row is "blocked on two names, and they are the two
that load a module by PATH". No tool change is needed.

## 2. `TestAgainstTheRealCorpus::test_the_whole_tree_has_one_dead_host_import_and_it_is_named`
## — two more dead host imports, one of them deliberate

```console
$ python3 -c "import tools.formal_host_import_shapes as S; print(dict(S.dead_host_imports('.')))"
{'fire_compiler.py': ['abc.abstractmethod'],
 'tools/formal_doc_index.py': ['subprocess'],
 'tools/formal_metamorph.py': ['subprocess']}
```

The ratchet at `test_formal_host_import_shapes.py:381` expects
`{"fire_compiler.py": ["abc.abstractmethod"]}`. The two new rows are different
from each other, which is why this is two decisions and not one:

* **`tools/formal_doc_index.py:68` — `import subprocess` with no other
  occurrence in the file.** A genuinely dead import: the name is bound and
  never read. It blocks the file for exactly the reason the test's own message
  gives, so **delete the line**.
* **`tools/formal_metamorph.py:148` — `import subprocess  # noqa: F401 —
  re-exported for callers that shim this module`.** This one is DELIBERATE and
  says so, but `dead_host_imports` reads the module alone and cannot see a
  caller reaching `formal_metamorph.subprocess`. So either the tool should
  learn the re-export shape (a `# noqa: F401`-marked binding other files read
  as an attribute is not dead) or the ratchet should name this row with the
  reason. **The first is the better fix and the second is the cheap one.**

**Next step:** delete the `formal_doc_index.py` line, then either teach
`dead_host_imports` about the re-export or add the `formal_metamorph.py` row to
the expected dict with the `noqa` reason, so the ratchet is about a NEW dead
import again rather than the two it has been carrying.
