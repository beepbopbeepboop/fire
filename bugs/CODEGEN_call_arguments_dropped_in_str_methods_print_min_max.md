# CODEGEN: keyword/extra arguments of str methods, print() and min/max/sum are ignored or rejected

Found 2026-11-20 by `tools/pydiff.py` (runs a program through CPython and through this compiler and compares).
The differences below are CPython versus the compiled binary.

Arguments are dropped: `print(sep=, end=)`, `str.split(sep, maxsplit)`, `strip(chars)`, `replace(old, new, count)`, `zfill`, `ljust/rjust/center`; `sum(x, start)` fails in gcc ("too many arguments to function mojo_sum"). Each method must accept exactly the arguments Python accepts. Fix one method at a time; each fix gets a line in the repro.

## Repro `print_sep_end.py`

```python
def main():
    print("a", "b", sep="")
    print("a", "b", sep="-")
    print("x", end="")
    print("y")
    print("p", "q", sep=", ", end="!\n")
main()
```

Differences:

```
line 1: CPython 'ab'   compiled 'a b'
line 2: CPython 'a-b'   compiled 'a b'
line 3: CPython 'xy'   compiled 'x'
line 4: CPython 'p, q!'   compiled 'y'
line 5: CPython ''   compiled 'p q'
line 6: CPython '<no line>'   compiled ''
```

## Repro `str_methods.py`

```python
def main():
    print("a,b,,c".split(",", 1))
    print("xxhixx".strip("x"))
    print("xxhixx".lstrip("x"))
    print("aaaaaa".replace("aa", "a", 1))
    print("42".zfill(5))
    print("ab".ljust(5) + "|")
    print("ab".rjust(5) + "|")
    print("ab".center(6) + "|")
    print("the quick  brown fox".split(" "))
    print(int("1000"))
    print(int("ff", 16))
    print(len("a\tb"))
main()
```

Differences:

```
line 1: CPython "['a', 'b,,c']"   compiled "['a', 'b', '', 'c']"
line 2: CPython 'hi'   compiled 'xxhixx'
line 4: CPython 'aaaaa'   compiled 'aaa'
line 5: CPython '00042'   compiled '0'
line 6: CPython 'ab   |'   compiled '|'
line 7: CPython '   ab|'   compiled '|'
line 8: CPython '  ab  |'   compiled '|'
```

## Repro `minmax_args.py`

```python
def main():
    print(max(1, 2, 3))
    print(min(4, 2, 9, 1))
    print(max([1, 5, 2]))
    print(sum([1, 2, 3], 10))
    print(max(["a", "bb", "c"], key=len))
    print(min(3, 2.5))
    print(divmod(-7, 2))
    print(pow(2, 10))
    print(round(2.675, 2))
main()
```

Differences:

```
/private/tmp/claude-505/-Users-mrs-net-chatgpt-claude-mojo-reference2/9262ca66-b12e-40f2-8a31-7a87a5021bd2/scratchpad/min/minmax_args.py:5:10: error: too many arguments to function 'mojo_sum'; expected 1, have 2
```

## Done when

Save each repro as a `.py` file and run

    python3 tools/pydiff.py <file>...

and every one prints `OK`. Add the repros as cases to `test_gimple_runner.py` (`test_gimple_matches_cpython(name, src)`), then delete this doc in the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
