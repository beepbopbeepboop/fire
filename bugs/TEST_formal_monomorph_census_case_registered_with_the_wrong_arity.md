# TEST_formal_monomorph_census_case_registered_with_the_wrong_arity: `test_formal_monomorph.py` reports an ERROR for a case that takes no `tmpdir`

**Area:** `test_formal_monomorph.py` (the harness and one registered case).
Found 2026-10-04 on `work/formal25-1`, while adding the value-bracket-argument
cases to that file. **Pre-existing on master**, proved below rather than
asserted: the branch's diff does not touch either the harness or the case, and
the failure reproduces at `master`'s own signature.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_monomorph.py
...
  PASS  the census answers each of the five questions
  ERROR the census reads the measured shapes out of the corpus
        TypeError: test_the_census_reads_the_measured_shapes_out_of_the_corpus()
        takes 0 positional arguments but 1 was given
formal monomorphization: PASS=19 EXPECTED=0 SKIP=0 FAIL=1
```

## What I saw

**The harness calls every registered case with `tmpdir`, and this one takes no
argument.** `main()`'s loop is `fn(tmpdir)` for the whole `TESTS` table, so a
case whose signature has no parameter raises a `TypeError` before its body runs,
is caught by the generic `except Exception`, and is reported as `ERROR` rather
than as the `FAIL` the same state means everywhere else in the tree.

The case itself is `test_the_census_reads_the_measured_shapes_out_of_the_corpus`
at `test_formal_monomorph.py:1336`, whose own docstring says what it is for:

> Skipped, with the reason printed and counted, when there is no stdlib checkout
> beside this tree — see `_Skip` and `_stdlib_dir`.

It reads the corpus, not a temporary tree, so it has no use for `tmpdir`. That
is not a defect in the case; it is a registration that does not match the
harness's calling convention.

## Why it is pre-existing

Both halves are at `master`, checked out of the object store rather than out of
the working tree (there is no `git checkout <path>` in this pass):

```console
$ git show HEAD:test_formal_monomorph.py | grep -n 'def test_the_census_reads_the_measured_shapes_out_of_the_corpus'
1336:def test_the_census_reads_the_measured_shapes_out_of_the_corpus():
$ git show HEAD:test_formal_monomorph.py | grep -n 'fn(tmpdir)'
1539:                    fn(tmpdir)
```

The branch's diff to that file is additive (`git diff --stat` at the time of
this note: `test_formal_monomorph.py | 142 +++`, two new cases and two new
`TESTS` rows) and touches neither line 1336 nor the loop.

## What it costs, and why it is not tidiness

`test_formal_monomorph.py` is a registered gate job (`formal-monomorph`), so
this is **a red suite on every gate**, and the red row is a case that would
otherwise be the check that the measurement in
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
§1–2 and the instrument that took it still agree. A row that can never run is
worse than a red row: it is a hole in coverage wearing a failure's clothes,
which is the distinction the sibling `TEST_*` docs in `bugs/` are about.

It also reads as "the census is broken", because `ERROR` on a census case is
indistinguishable from a census that raises — and the `_Skip` path it documents
(silence for a tree with no stdlib beside it) is exactly what a reader would
want to see instead.

## The next step

One of the two, and both are one line:

* **give the case the parameter** — `def test_the_census_reads_the_measured_shapes_out_of_the_corpus(tmpdir)` and leave it unused, which is what every other case in the table already looks like; or
* **let the table say how a case is called** — a `(name, fn, *args)` third element, or a `fn` attribute on the case. This is the better shape if more cases read the corpus rather than a tree, because it stops the convention from being re-broken silently.

Do **not** add the row to `EXPECTED_FAILURES`: that table forgives a case that
fails, and this one never reaches its body, so the marker would forgive a
`TypeError` in the harness rather than a known gap in the census.