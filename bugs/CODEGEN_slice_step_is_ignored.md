# CODEGEN: slicing with a step (s[::2], s[::-1], lst[4:1:-1]) ignores the step

Found 2026-11-20 by `tools/pydiff.py` (runs a program through CPython and through this compiler and compares).
The differences below are CPython versus the compiled binary.

`s[::2]` returns the whole string, `s[::-1]` returns it unreversed. Both strings and lists. Find the slice lowering (grep `SliceExpr` in `mojo/backend_gimple/emit_exprs.py`) and pass the step through to the runtime slice helper; add a helper variant if none takes a step. A negative step swaps the default start and stop.

## Repro `slice_step.py`

```python
def main():
    s = "abcdefgh"
    print(s[::2])
    print(s[1::2])
    print(s[::-1])
    lst = [0, 1, 2, 3, 4, 5]
    print(lst[::2])
    print(lst[::-1])
    print(lst[4:1:-1])
main()
```

Differences:

```
line 1: CPython 'aceg'   compiled 'abcdefgh'
line 2: CPython 'bdfh'   compiled 'bcdefgh'
line 3: CPython 'hgfedcba'   compiled 'abcdefgh'
```

## Done when

Save each repro as a `.py` file and run

    python3 tools/pydiff.py <file>...

and every one prints `OK`. Add the repros as cases to `test_gimple_runner.py` (`test_gimple_matches_cpython(name, src)`), then delete this doc in the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
