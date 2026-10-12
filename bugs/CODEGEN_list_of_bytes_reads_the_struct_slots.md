# CODEGEN: `list(b"cd")` reads the `MojoBytes` struct as a list of its slots

**Area:** CODEGEN (`mojo/backend_gimple`). **Status: OPEN, measured
2026-10-07, PRE-EXISTING on `master`.** Found while fixing the interpreter's
`for x in b"ab"` bug (it yielded characters where CPython yields ints, and the
compiled path was right), whose own exact next step asked to pin `list(b"cd")`
three ways. The interpreter half is fixed; the compiled half is this, which is
why the pinned case in `test_runtime_diff.py` (`bytes_iterates_as_ints`)
deliberately covers the `for`/index/equality shapes and not `list(bytes)`.

## What I ran

```
$ printf 'def main():\n    x = list(b"cd")\n    print(len(x))\n    print(x[0])\n    print(list(b"cd"))\n    print(list("cd"))\n' > .tmp/listbytes.mojo
$ python3 fire.py run .tmp/listbytes.mojo
2
99
[99, 100]
['c', 'd']
$ python3 fire.py --jit .tmp/listbytes.mojo
5
4379413504
[4379415312, 4379415328, 4379415344, 4379415360, 4379415376]
['c', 'd']
```

`list("cd")` is correct; `list(b"cd")` is not. The `len` of 5 and the five
ascending pointer-sized values are the `MojoBytes` struct's own fields read as
if the object were a `MojoList` — the bytes value is being handed to the list
builtin without an element-kind/element-source decision, so it is treated as a
list whose elements are the struct's slots. CPython and the interpreter both
say `2` / `[99, 100]`.

## Why it matters

`list(b"...")` is a plain, ordinary expression, and the compiled path answers
it with a plausible-looking container of addresses and exits 0 — the silent
wrong-answer class the refusal discipline exists to avoid. It is upstream of
nothing in this task, but it is the reason the interpreter fix could not be
pinned with the `list(b"cd")` line its own doc suggested.

## The exact next step

`list(x)` lowering needs a bytes arm beside its list/str/iterable arms: a
`MojoBytes *` operand should produce a `MojoList *` of `mojo_bytes_get(b, i)`
for `i in 0..mojo_bytes_len(b)`, which is exactly the element source
`mojo/backend_gimple/emit_loops.py`'s `_gen_for_bytes` already uses. The
cheapest measurement is the four-line probe above through `fire.py --jit`.

When it is fixed, add the `list(b"cd")` line to
`test_runtime_diff.py`'s `bytes_iterates_as_ints` and delete this doc. Do not
name the deleted interpreter doc: the symptom is "`for x in b\"ab\"` yielded
characters on the interpreter where CPython yields ints".
