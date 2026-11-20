# CODEGEN: items(), enumerate over a string, nested lists print element words as numbers; bools in a list print 1/0

Found 2026-11-20 by `tools/pydiff.py` (runs a program through CPython and through this compiler and compares).
The differences below are CPython versus the compiled binary.

Elements that are strings or nested containers print as a raw number like `4312620976`, and bools inside a list print as `1`/`0` instead of `True`/`False`. The element kind is known to the compiler where the list or tuple is built, but the printer is given an untyped word. Find where `print` of a list/tuple chooses the element printer and carry the element kind from the construction site (see `gen._elem_types`, `mojo_list_set_kinds`).

## Repro `ptr_print.py`

```python
def pair():
    return ("a", "b")

def main():
    print(pair())
    t = (-3.5, 3)
    print(t)
    d = {"ann": 3, "bo": 0}
    print(list(d.items()))
    print([(i, c) for i, c in enumerate("hi")])
    print([[1, 2], [3, [4, []]]])
main()
```

Differences:

```
line 3: CPython "[('ann', 3), ('bo', 0)]"   compiled '[4312620976, 4312621056]'
line 4: CPython "[(0, 'h'), (1, 'i')]"   compiled '[(0, 4312620768), (1, 4312621328)]'
line 5: CPython '[[1, 2], [3, [4, []]]]'   compiled '[[1, 2], [3, 4312621680]]'
```

## Repro `bool_print.py`

```python
def is_pos(n):
    return n > 0

def main():
    r = is_pos(3)
    print(r)
    print(is_pos(-1))
    flags = [is_pos(1), is_pos(-2)]
    print(flags)
    f = lambda n: n > 0
    print(f(5))
    print(not r)
    print(bool(""))
    print(bool("0"))
main()
```

Differences:

```
line 3: CPython '[True, False]'   compiled '[1, 0]'
```

## Done when

Save each repro as a `.py` file and run

    python3 tools/pydiff.py <file>...

and every one prints `OK`. Add the repros as cases to `test_gimple_runner.py` (`test_gimple_matches_cpython(name, src)`), then delete this doc in the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
