# INTERP: `for x in b"ab"` yields CHARACTERS on the interpreter, where CPython yields ints

**Area:** INTERP (`myinterpreter.py`). Found 2026-10-04 while fixing
`bugs/CODEGEN_zip_loop_target_keeps_the_first_loops_type.md` (fixed and
deleted): the compiled path turned out to be RIGHT about this and the
interpreter wrong, which is why that bug's regression could not be pinned
three ways and lives in `test_gimple_runner.py` instead.

## What I ran

```
$ printf 'def main():\n    for x in b"ab":\n        print(x)\n    print(list(b"cd"))\n' > b.py
$ python3 fire.py run b.py
a
b
['c', 'd']
$ python3 b.py
97
98
[99, 100]
```

CPython 3.14.7 on this machine. `fire.py run` prints the characters and the
CHARACTER LIST; the compiled path prints `97 98` and `[99, 100]` for the same
text (measured in the same session, by the case
`gimple_bytes_and_str_loop_targets_rebind` in `test_gimple_runner.py`, which
compares the compiled program against CPython and passes).

## Why it is worth fixing rather than pinning around

A `bytes` object is an `int` sequence, and almost everything built on it is an
`int` operation: `b[0]`, `b[0] + 1`, `len(b)`, `%` formatting, `bytes.hex()`,
`struct.unpack`, `int.from_bytes`. On this interpreter every one of those sees a
one-character string instead, so the failure is not confined to a `for` loop —
and a loop is where it is most visible, because a loop target is the only place
the value becomes the program's output directly.

It is also the kind of bug that makes a comparison suite agree with itself: the
interpreter and the compiled path disagree here, but the engine-vs-engine
comparisons that could see it (`test_runtime_diff.py`) have to be
CPython-comparable to be worth anything, and a program with a bytes iteration
in it fails CPython comparison for this reason alone. So the one suite built to
catch a shared bug cannot host this case, which is why the pinned case for the
compiled half lives in `test_gimple_runner.py`.

## Where to look

`myinterpreter.py`: the `for` statement's iteration protocol over a value whose
type is the `bytes` builtin. The three questions, in order:

1. what `b"ab"` evaluates to — whether the interpreter has a `MojoBytes` value
   at all, or boxes the literal as a `MojoString`;
2. the length/`__getitem__` pair the `for` lowering calls, if it goes through
   `__getitem__` at all;
3. `list(b"cd")`, which answers the same question by a different path and so
   tells you whether the bug is in the value or in the loop.

`gimple_codegen.py` is the working reference for the intended semantics —
`mojo_list_get_*` over a `MojoBytes *` with `mojo_bytes_get`/`mojo_bytes_len`
(`mojo/backend_gimple/emit_loops.py`'s `_gen_for_bytes`, which reads
`mojo_bytes_get (b, i)` — an int, 0-255 — and prints 97 for `b"a"`).

## Exact next step

Make the interpreter's `bytes` yield ints, then pin it three ways: add
`for_over_bytes_yields_ints` to `test_runtime_diff.py` and to `CPYTHON_COMPARABLE`
(it is plain Python, so CPython can be the oracle verbatim), and move
`gimple_bytes_and_str_loop_targets_rebind`'s bytes lines into it — that case is
in `test_gimple_runner.py` only because this bug made a three-way comparison
impossible.

While there: `print(b"ab")` and `b"ab" == b"ab"` on the interpreter, which this
session did not measure. A bytes literal that iterates as text is likely to
compare as text too, and `bytes` is hashable in CPython, so
`{b"a": 1}[b"a"]` is the case that would show it.