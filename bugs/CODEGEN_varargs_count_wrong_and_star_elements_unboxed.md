# CODEGEN: *args reports one extra element for zero extra arguments and prints string elements as numbers

Found 2026-11-20 by `tools/pydiff.py` (runs a program through CPython and through this compiler and compares).
The differences below are CPython versus the compiled binary.

`def show(first, *rest)` called as `show("a")` gives `len(rest) == 1` with `rest == [0]`; with strings it prints raw pointers. The packing at the call site adds a phantom element when no extra argument is passed, and the packed list has no element kinds. See `_pack_vararg_trailing_params` in `mojo/backend_gimple/emit_calls.py`.

## Repro `varargs.py`

```python
def total(*nums):
    s = 0
    for n in nums:
        s += n
    return s

def show(first, *rest):
    print(first, len(rest), list(rest))

def main():
    print(total())
    print(total(5))
    print(total(1, 2, 3))
    show("a")
    show("a", "b", "c")
    args = [1, 2, 3]
    print(total(*args))
main()
```

Differences:

```
line 4: CPython 'a 0 []'   compiled 'a 1 [0]'
line 5: CPython "a 2 ['b', 'c']"   compiled 'a 2 [4301523784, 4301523792]'
```

## Done when

Save each repro as a `.py` file and run

    python3 tools/pydiff.py <file>...

and every one prints `OK`. Add the repros as cases to `test_gimple_runner.py` (`test_gimple_matches_cpython(name, src)`), then delete this doc in the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
