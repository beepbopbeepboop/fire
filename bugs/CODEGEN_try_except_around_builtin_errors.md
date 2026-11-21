# CODEGEN: except around int("x"), d[missing], lst[99], 1//0 never catches

Found 2026-11-20 by `tools/pydiff.py` (runs a program through CPython and through this compiler and compares).
The differences below are CPython versus the compiled binary.

The builtin operations do not raise a catchable exception here: `safe_int("x")` returns 0 instead of reaching `except ValueError`; a missing key, a bad index and a division by zero print `0` where Python enters the handler. Decide per operation whether it raises or returns a sentinel, and make the `try` machinery see it. Start with `int(str)` and `1 // 0`.

## Repro `try_except.py`

```python
def safe_int(s):
    try:
        return int(s)
    except ValueError:
        return -1

def main():
    print(safe_int("12"))
    print(safe_int("x"))
    d = {"a": 1}
    try:
        print(d["zz"])
    except KeyError:
        print("no key")
    try:
        print([1, 2][99])
    except IndexError:
        print("no index")
    try:
        print(1 // 0)
    except ZeroDivisionError:
        print("div zero")
    finally:
        print("finally")
main()
```

Differences:

```
line 2: CPython '-1'   compiled '0'
line 3: CPython 'no key'   compiled '0'
line 4: CPython 'no index'   compiled '0'
```

## Done when

Save each repro as a `.py` file and run

    python3 tools/pydiff.py <file>...

and every one prints `OK`. Add the repros as cases to `test_gimple_runner.py` (`test_gimple_matches_cpython(name, src)`), then delete this doc in the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
