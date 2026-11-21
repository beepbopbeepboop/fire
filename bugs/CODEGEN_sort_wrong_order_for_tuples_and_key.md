# CODEGEN: sorted()/list.sort() give the wrong order for tuples and with key=

Found 2026-11-20 by `tools/pydiff.py` (runs a program through CPython and through this compiler and compares).
The differences below are CPython versus the compiled binary.

Sorting a list of tuples, or with `key=`, returns the wrong order (or `None` where `0` was). Plain ints and plain strings work. Find how `sorted`/`.sort` are lowered (grep `mojo_list_sort` in `mojo/backend_gimple/` and `runtime/fire_runtime.c`): tuples compare element by element, `key=` calls the key function on each element first and compares the keys. Sort must be stable.

## Repro `sort_key.py`

```python
def main():
    words = ["pear", "Apple", "fig", "banana", ""]
    print(sorted(words, key=len))
    print(sorted(words, key=lambda w: w.lower()))
    nums = [3, -7, 2, 0, -1]
    print(sorted(nums, key=abs))
    print(sorted(nums, key=lambda n: -n))
main()
```

Differences:

```
line 3: CPython '[0, -1, 2, 3, -7]'   compiled '[None, -1, 2, 3, -7]'
line 4: CPython '[3, 2, 0, -1, -7]'   compiled '[3, 2, None, -1, -7]'
```

## Repro `sort_tuples.py`

```python
def main():
    pairs = [("bob", 3), ("al", 3), ("cy", 1), ("al", 0)]
    print(sorted(pairs))
    print(sorted(pairs, key=lambda p: p[1]))
    pairs.sort(key=lambda p: p[0])
    print(pairs)
main()
```

Differences:

```
line 1: CPython "[('al', 0), ('al', 3), ('bob', 3), ('cy', 1)]"   compiled "[('bob', 3), ('al', 3), ('cy', 1), ('al', 0)]"
line 3: CPython "[('al', 3), ('al', 0), ('bob', 3), ('cy', 1)]"   compiled "[('bob', 3), ('al', 3), ('al', 0), ('cy', 1)]"
```

## Done when

Save each repro as a `.py` file and run

    python3 tools/pydiff.py <file>...

and every one prints `OK`. Add the repros as cases to `test_gimple_runner.py` (`test_gimple_matches_cpython(name, src)`), then delete this doc in the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
