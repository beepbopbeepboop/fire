# CODEGEN: None prints as 0; `0 is None` is True; a parameter default None cannot be told from 0

Found 2026-11-20 by `tools/pydiff.py` (runs a program through CPython and through this compiler and compares).
The differences below are CPython versus the compiled binary.

The biggest cluster (about 60 of 240 corpus programs): a `None` stored in a variable, list slot, dict value, return value or parameter is the integer word 0 at run time, so `print(None)` shows `0`, `d.get(k)` of a missing key shows `0`, `0 is None` is True and `label(0)` takes the `None` branch. This is a REPRESENTATION problem, not one missing case: `int64_t` is used for an int, for None and for an erased pointer alike (see `doc/GIR.md` stage 5b). Do NOT make `x == None` mean `x == 0`: an earlier attempt did exactly that and broke six runtime cases (see `bugs/CODEGEN_none_passed_to_a_parameter_is_not_none.md`). Needed first: a decision, written into this doc, on how a possibly-None value is represented (a boxed word, a separate present flag, or a reserved bit pattern) and which static types use it.

## Repro `none_print.py`

```python
def find(items, target):
    i = 0
    for x in items:
        if x == target:
            return i
        i += 1
    return None

def main():
    print(find([5, 0], 9))
    print(find([5, 0], 5))
    d = {"a": 1}
    print(d.get("zz"))
    x = None
    print(x)
    print([None, 1])
    print([0, 1])
    print(f"{x}")
    print(str(None))
main()
```

Differences:

```
line 1: CPython 'None'   compiled '0'
line 3: CPython 'None'   compiled '0'
line 4: CPython 'None'   compiled '0'
line 7: CPython 'None'   compiled '0'
line 8: CPython 'None'   compiled '0'
```

## Repro `none_vs_zero.py`

```python
def label(value=None):
    if value is None:
        return "missing"
    if value == 0:
        return "zero"
    return "value"

def main():
    print(label())
    print(label(None))
    print(label(0))
    print(label(-1))
    print(0 == None)
    print(None == None)
    n = 0
    print(n is None)
    print([0, 1, 2][0])
    lst = [0, 1]
    print(lst)
    print(None in [0, 1])
    print(0 in [None, 1])
main()
```

Differences:

```
line 3: CPython 'zero'   compiled 'missing'
line 7: CPython 'False'   compiled 'True'
```

## Done when

Save each repro as a `.py` file and run

    python3 tools/pydiff.py <file>...

and every one prints `OK`. Add the repros as cases to `test_gimple_runner.py` (`test_gimple_matches_cpython(name, src)`), then delete this doc in the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
