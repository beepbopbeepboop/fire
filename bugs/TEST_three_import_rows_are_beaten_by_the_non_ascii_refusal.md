# TEST_three_import_rows_are_beaten_by_the_non_ascii_refusal: three rows of `test_formal_imports.py` assert on a refusal a later refusal now pre-empts

**Area:** the test suite's own fixtures — `test_formal_imports.py`, three rows.
**Not** the compiler and **not** `formal/imports.py`: in all three cases the
refusal that fires is CORRECT, and the rows fail because the file each of them
builds stopped being the case they are about. **Status: OPEN, measured
2026-10-05 on `work/formal27-6` at `93747a29`, and proven pre-existing** — the
same three rows, same messages, on this branch's base commit `166ec813` with
nothing of this round's changes applied (§2).

**No claim covers this.** `bugs/TEST_two_stale_refusal_needles_in_the_formal_suites.md`
is the same SHAPE (a refusal became more accurate and a suite's expectation did
not follow) but a different pair of files and a different mechanism: that one is
a NEEDLE — a test asserting on the WORDING of a message that is now worded
differently. This one is a FIXTURE that has become a different program, so the
build refuses earlier and the needle the row checks for is never printed at all.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
  FAIL  a function-local import is a dependency
  FAIL  widening the imported list widens nothing else
  FAIL  a standard-library module in no tier is not reported as a typo
formal imports: PASS=69 EXPECTED=0 SKIP=0 FAIL=3
```

and, for the pre-existence measurement:

```console
$ git worktree add --detach .tmp/headcheck 166ec813 && cd .tmp/headcheck
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
  FAIL  a function-local import is a dependency
  FAIL  widening the imported list widens nothing else
  FAIL  a standard-library module in no tier is not reported as a typo
formal imports: PASS=69 EXPECTED=0 SKIP=0 FAIL=3
$ git worktree remove --force .tmp/headcheck
```

## What I saw

**All three report the same tail**, and it is not the message each row is about:

```
… one that reads plausible: for `s = "héllo"`, `s[0]` is 104 and `s[2]` is 108,
which is `l`, and the wrong answers are the right answers for the NEIGHBOURING
indices. What this path CAN do: keep the text ASCII …
```

That is `formal/model.py`'s **non-ASCII string-subscript refusal**, added
2026-10-04 in `f9ffd4c0` (*"formal: the encoding condition is a fact about the
IMAGE, not the MODULE"*). `formal/build.py` now publishes every module's
non-ASCII literals before compiling anything
(`M.publish_non_ascii_strings(M.non_ascii_strings_in(stmts))`), so a file that
contains one is refused at that check, BEFORE the import chain is walked and
before `formal/imports.py::unresolvable_import_error` can be reached.

**The three fixtures, and what each row is actually about:**

| row | the file it builds | what the row asserts | non-ASCII literals in that file |
|---|---|---|---:|
| `a function-local import is a dependency` | `test_runtime_header_scan.py` | the refusal NAMES the import (`imports 'reflect'`), because a function-local import is on the link line | **3** |
| `a standard-library module in no tier is not reported as a typo` | a scratch fixture that imports `shlex` | `shlex` is refused as a CPython standard-library module and not as a typo | the row's own scratch fixture, whose text carries the em-dashes of this sentence |
| `widening the imported list widens nothing else` | a scratch corpus, same tree | adding a name to one module's imports widens no other module's | same |

Measured with the backend's own reader, which is the one the build uses:

```console
$ python3 -c "
import sys; sys.path.insert(0, '.')
import formal.model as M, formal.build as B
for f in ('test_runtime_header_scan.py', 'test_formal_imports.py'):
    stmts = B.parse_module(open(f, encoding='utf-8').read(), f)
    print(f, len(M.non_ascii_strings_in(stmts)))"
test_runtime_header_scan.py 3
test_formal_imports.py 32
```

**So this is the encoding refusal working as designed, and it is a
`formal-imports` GATE JOB that is red with no `expect=`.** `tools/suite.py`
registers it with `test('formal-imports', [PY, 'test_formal_imports.py'], …)` and
no marker, so `make check` is red on `master` over three rows whose subject is
untouched.

## What I expected

Each of the three rows asserts a property of the IMPORT surface, and each
asserts it by building a whole file and reading the refusal. Two of them build a
file the test itself writes, so their fixtures should be ASCII by construction —
and the first builds `test_runtime_header_scan.py`, a **repository file whose
contents another worker edits**, which is a dependency this row never intended:
the day that file gains an em-dash in a docstring, the row stops being about
function-local imports and becomes about the encoding refusal.

## The exact next step

**Give each row a fixture it owns, rather than a repository file whose subject
is somebody else's change.** Concretely:

1. `a function-local import is a dependency` should build a scratch module
   written by the test, containing `import reflect` inside a `def` body and an
   ASCII-only docstring — the row already asserts the property directly against
   `imported_modules` on a hand-written `src`, so the end-to-end half needs the
   same source written to disk. The chain it wants is reached through
   `reflect` → `importlib` (a host module), which is what makes the file refused
   for an import reason at all; that part is about the fixture's IMPORTS, not
   its prose.
2. The two scratch-fixture rows should assert their fixture is ASCII before
   building it, so the precondition is stated rather than discovered — the same
   shape `tools/formal_host_import_wall.py`'s `module_imports is None` row takes
   for a file it cannot read. A one-line check
   (`M.non_ascii_strings_in(parse_module(src)) == []`) turns "this row failed for
   an unrelated reason" into a message that says which reason.
3. **Do not weaken the encoding refusal and do not mark the rows `expect=`.**
   The refusal is correct — `s[0]` on `"héllo"` really is the wrong byte — and
   `bugs/TEST_two_stale_refusal_needles_in_the_formal_suites.md` §2 is the
   precedent for that judgement on the sibling shape.

A fourth thing worth doing while in there, and it is the general form of this
bug: **a row that builds a repository FILE should say so in its own message**,
because the failure it produces reads like a compiler bug and is a fixture
problem. `test_runtime_header_scan.py` is a real corpus file with a real
function-local import, so keeping it as the witness is defensible — but then the
row needs an ASCII precondition on that file, and if the file ever grows a
non-ASCII docstring the row should say "the fixture changed" rather than print a
refusal about string subscripts.