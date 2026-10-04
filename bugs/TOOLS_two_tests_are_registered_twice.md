# Two tests are registered TWICE in `tools/suite.py`, and the first registration is dead code

**Area:** `tools/suite.py` · **filed 2026-10-04 during the formal21 merge, NOT
fixed** · pre-existing on `master` (`8b1ab466`), not a merge regression

`test()` writes into a dict:

```python
def test(*a, **kw) -> Spec:
    s = Spec(*a, **kw)
    REGISTRY[s.name] = s
    return s
```

so a second `test('formal-glob', …)` silently REPLACES the first. Two names are
written twice, 46 lines apart in each case:

```
$ grep -n "test('formal-field-walk'" tools/suite.py
2783:test('formal-field-walk', [PY, 'test_formal_field_walk.py'], mem='tiny',
2937:test('formal-field-walk', [PY, 'test_formal_field_walk.py'], mem='tiny',

$ grep -n "test('formal-glob'" tools/suite.py
2943:test('formal-glob', [PY, 'test_formal_glob.py'], mem='tiny',
2989:test('formal-glob', [PY, 'test_formal_glob.py'], mem='tiny',
```

Each pair came from a different commit — `5b2e62c3` ("Register master's two
unregistered test files") and `574d9135` ("Register formal-field-walk and
formal-glob") — and neither looked for the other, so the second is the one that
runs and the first is a comment block plus a call that computes a `Spec` and
throws it away.

## Why nothing is red

Nothing has to be. The name resolves to one row, the row that survives is the
later one, and the earlier one costs a dict store. `test_suite.py` passes
(308/308) with these in place, and `--list` shows one line each. That is exactly
what makes it worth filing rather than leaving: the second registration's
`desc` is the one a reader sees, and for `formal-glob` the two `desc`s disagree
("glob: CPython's own glob, both backends, 6 groups" against "glob: has_magic,
hidden files, symlinks and escapes, against CPython"), so the sentence in the
registry is whichever commit landed last.

## Next step

Delete the earlier `test(...)` call and its comment in both cases, keeping the
later row — which is the one that runs today, so nothing about any run changes.
The check that would have caught this does not exist and is worth adding beside
it: `test_suite.py`'s estate check already refuses a registered file that no spec
runs and a registered spec in no bucket, and the missing third question is the
one whose answer is a dict — "is any name registered twice", which is a two-line
loop over `tools/suite.py`'s source rather than over the registry, because the
registry cannot see the overwrite that already happened.

Not done here on purpose: `tools/suite.py` is not this merge's area, and the fix
is a deletion in a file several workers are editing at once.