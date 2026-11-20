# CODEGEN: `x /= 2` and `x += 0.5` on an int variable truncate (`type(x).__name__` fixed 2026-11-20)

Found 2026-11-20 by `tools/pydiff.py` (runs a program through CPython and through this compiler and compares).
The differences below are CPython versus the compiled binary.

An int variable that gets a float in an augmented assignment keeps the int type and truncates (`x = 9; x /= 2` prints 4, Python prints 4.5), and `if 0.0001:` is treated as false. Use CPython as the oracle.

## Repro `float_arith.py`

```python
def main():
    x = 9
    x /= 2
    print(x)
    y = 13
    y += 0.5
    print(y)
    print(7 / 2)
    print(1e-9 > 0)
    if 0.0001:
        print("tiny truthy")
    print(3 == 3.0)
    print(round(2.5), round(3.5))
main()
```

Differences:

```
line 1: CPython '4.5'   compiled '4'
line 2: CPython '13.5'   compiled '13'
line 5: CPython 'tiny truthy'   compiled 'True'
line 6: CPython 'True'   compiled '2 4'
line 7: CPython '2 4'   compiled ''
line 8: CPython ''   compiled '<no line>'
```

## Done when

Save each repro as a `.py` file and run

    python3 tools/pydiff.py <file>...

and every one prints `OK`. Add the repros as cases to `test_gimple_runner.py` (`test_gimple_matches_cpython(name, src)`), then delete this doc in the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
