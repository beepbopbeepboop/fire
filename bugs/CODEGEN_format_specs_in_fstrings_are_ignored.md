# CODEGEN: f-string format specs (:^6, :.2f, :04d, :x, :b) are partly ignored

Found 2026-11-20 by `tools/pydiff.py` (runs a program through CPython and through this compiler and compares).
The differences below are CPython versus the compiled binary.

Center alignment `:^N`, precision `:.2f` on a float, zero padding with a sign `:04d` on a negative number, and the radix types `:x` `:b` are ignored or wrong. `:<N` and `:>N` work. Find the format-spec lowering (grep `format_spec` in `mojo/backend_gimple/`) and add the missing cases. Compare against Python for negative numbers, zero and wide values.

## Repro `fstring_spec.py`

```python
def main():
    s = "ab"
    n = -3
    x = 3.14159
    print(f"[{s:<5}]")
    print(f"[{s:>5}]")
    print(f"[{s:^6}]")
    print(f"[{n:^5}]")
    print(f"{x:.2f}")
    print(f"{n:04d}")
    print(f"{255:x}")
    print(f"{5:b}")
    print(f"{42:5d}|")
main()
```

Differences:

```
line 4: CPython '[ -3  ]'   compiled '[  -3 ]'
line 5: CPython '3.14'   compiled '3.14159'
line 6: CPython '-003'   compiled '00-3'
line 7: CPython 'ff'   compiled '255'
line 8: CPython '101'   compiled '5'
```

## Done when

Save each repro as a `.py` file and run

    python3 tools/pydiff.py <file>...

and every one prints `OK`. Add the repros as cases to `test_gimple_runner.py` (`test_gimple_matches_cpython(name, src)`), then delete this doc in the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
