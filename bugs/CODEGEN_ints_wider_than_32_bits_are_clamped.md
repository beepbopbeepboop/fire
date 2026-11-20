# CODEGEN: integer results above 2**31 are clamped to 2147483647 or 0

Found 2026-11-20 by `tools/pydiff.py` (runs a program through CPython and through this compiler and compares).
The differences below are CPython versus the compiled binary.

`2 ** 62` prints `2147483647`, `1 << 40` prints `0`, `10 ** 12` prints `2147483647`. The literal 3000000000 works, so the problem is in `**` and `<<` (likely a runtime helper typed `int`/`int32_t`). Find the helpers (grep `mojo_pow`, `mojo_lshift` in `runtime/fire_runtime.c`) and check their parameter and return types.

## Repro `big_int.py`

```python
def main():
    a = 2 ** 62
    print(a)
    b = 4611686018427387904
    print(b)
    c = 3000000000
    print(c)
    print(c + 1)
    print(1 << 40)
    print(10 ** 12)
main()
```

Differences:

```
line 1: CPython '4611686018427387904'   compiled '2147483647'
line 5: CPython '1099511627776'   compiled '0'
line 6: CPython '1000000000000'   compiled '2147483647'
```

## Done when

Save each repro as a `.py` file and run

    python3 tools/pydiff.py <file>...

and every one prints `OK`. Add the repros as cases to `test_gimple_runner.py` (`test_gimple_matches_cpython(name, src)`), then delete this doc in the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
