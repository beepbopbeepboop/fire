# suite-self-test is red: `test_formal_glob.py` is neither registered nor declared

**Area:** TOOLS (the registry estate). NOT `project22:native-decide`'s — filed by
a worker whose subject was the axiom census, which ran `test_suite.py` and found
this already red on `master`. Its sibling half, `test_formal_field_walk.py`, has
its own doc (`bugs/TOOLS_test_formal_field_walk_is_neither_registered_nor_
declared.md`); this one has none, and `test_suite.py`'s estate check names both
in one message, so the row reads as if the existing doc covered it.

## What I ran

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_suite.py -j1
    ...
    Results: 298 passed, 1 failed
      - the estate: every test file is run by something, or says why not:
        not run by any registered spec and not in UNREGISTERED:
        test_formal_field_walk.py, test_formal_glob.py

## What I saw

`test_suite.py`'s `UNREGISTERED` table has no entry for either file
(`git show master:test_suite.py | grep -c "test_formal_glob.py"` → 0), so the
estate check fails on the row naming them BOTH.  Verified this is not mine: my
only change to `test_suite.py` is `+36` lines excusing `test_formal_axioms.py`,
and `git diff master --stat test_suite.py` shows nothing else — and the same
failure reproduces with my new file's entry removed, because neither of these two
files is in the table on `master` either.

`test_formal_glob.py` is the 33-case `glob` corpus: every case compares the
built arm64 image and the built x86-64 image against CPython's own `glob`, which
is why it was left unregistered (it BUILDS AND RUNS images on both backends, the
same shape as the `_FORMAL_SUITE_REASON` group twenty entries above it).  It is
not in that group either, which is the gap.

## What it is not

Not a failure of either test.  Both are green when run directly; what is red is
the suite-self-test's own row, which exists to make an unaccounted-for test file
impossible.

## Exact next step

Two lines, both in `tools/suite.py` / `test_suite.py`, either of which closes the
row:

1. **Declare it.** Add `'test_formal_glob.py': _FORMAL_SUITE_REASON,` to
   `test_suite.py`'s `UNREGISTERED` — it is the same shape as the fifteen
   entries above it and the reason is already written once.
2. **Register it**, which is what CLAUDE.md's cost rule wants for a corpus of
   this size. The exact spec, beside `formal-globals` in the `check` bucket:

       test('formal-glob', [PY, 'test_formal_glob.py'], deps=['preflight'],
            extra=['test_formal_glob.py', 'test_formal_dylib.py',
                   'test_formal_json.py', 'formal/hostmods/glob.mojo',
                   'formal/hostmods/fnmatch.mojo', 'formal/hostmods/os/path/'
                   '__init__.mojo', 'formal/build.py', 'formal/model.py',
                   'formal/imports.py'] + FORMAL_BUILD_INPUTS,
            desc='the glob corpus on both architectures against CPython\'s glob')

   Measure it before naming a memory class: the suite's own registry comment says
   `ADMITTED_COUNTS`-scale suites here have never been given a `MEASURED_PEAK_GB`,
   and a `mem=` value guessed from the shape is the over-provisioning the class
   ladder argues against. One measured run, then the number.

Either way, doing both halves of the estate row at once — `test_formal_glob.py`
and `test_formal_field_walk.py` — is what the message is asking for: it prints
them in one failure, so a fix that excuses one and not the other leaves the row
red.