# TEST_test_formal_monomorph_calls_a_zero_argument_test_with_one

**Status: open, one-line fix, not made here.** Found by running the registered
`formal-monomorph` job while checking documents (branch
`work/formal24-docs-truth`, whose subject is FORMAL.md / `doc/ABI.md` /
`OPUS.md`). `test_formal_monomorph.py` is not in this branch's write set and the
failure predates it — `git diff master -- test_formal_monomorph.py` is empty on
this branch — so it is filed rather than edited.

## What I ran and what I saw

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 test_formal_monomorph.py
```

```
  PASS  a stated mangled spelling is the one the mangler produces
  ERROR the census reads the measured shapes out of the corpus
        TypeError: test_the_census_reads_the_measured_shapes_out_of_the_corpus() takes 0 positional arguments but 1 was given

formal monomorphization: PASS=17 EXPECTED=0 SKIP=0 FAIL=1
```

## The cause

`test_formal_monomorph.py`'s runner passes the scratch directory to every case:

```python
                    fn(tmpdir)          # :1539
```

and one case in the `CASES` table takes none:

```python
def test_the_census_reads_the_measured_shapes_out_of_the_corpus():   # :1336
...
    ("the census reads the measured shapes out of the corpus",
     test_the_census_reads_the_measured_shapes_out_of_the_corpus),   # :1515
```

So the case raises `TypeError` before its first assertion. The `ERROR` is
reported rather than swallowed (`except Exception ... print(f"  ERROR ...")`),
which is why the tally says `FAIL=1` rather than quietly passing — the runner is
right and the case is wrong.

## Why it matters more than one red line

The case is one of the five that make the monomorphization census mean anything:
it is the half that asks the REAL STDLIB for the shapes the prose measured,
against the three symbols `bugs/FORMAL_a_bare_call_to_a_template_whose_type_
arguments_are_inferrable.md` §1 names. So the suite is reporting "the census
answers each of the five questions" (a static check over the module's own data)
while the case that asks the corpus is not running at all. That is the
`FILES BLOCKED IS AN UPPER BOUND` shape applied to a test file: a coverage-looking
claim that is green because the thing that would contradict it never ran.

It is also not marked. `formal-monomorph` is a registered `mem='tiny'` job in
`tools/suite.py` with no `expect=` and no `disabled=`, so this is an **undeclared
red** — a failing registered test that no marker accounts for, which is the class
`CLAUDE.md`'s `expect=`/anti-rot discipline exists to make impossible.

## The fix

Do not special-case the one function. The runner's contract should say what it
means, once:

```python
import inspect
...
                    fn(tmpdir) if inspect.signature(fn).parameters else fn()
```

or, if every case should take the directory, give
`test_the_census_reads_the_measured_shapes_out_of_the_corpus` a `tmpdir`
parameter and use it (or `_tmpdir`) — which is the better of the two, because a
uniform signature is what stops the next zero-argument case from failing the same
way. Then re-run and confirm the case reports its own verdict rather than an
`ERROR`.

## What to check afterwards

`python3 test_formal_monomorph.py` should read `PASS=18 FAIL=0`, and
`bugs/FORMAL_generic_monomorph_scope.md`'s claim that the scope is measured
rather than assumed becomes true of this case too.
