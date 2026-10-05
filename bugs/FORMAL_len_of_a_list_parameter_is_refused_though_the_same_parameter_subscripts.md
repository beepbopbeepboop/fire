# `len(xs)` on a LIST PARAMETER is refused as `len() of a value classified as 'int'`, while `xs[i]` on the same parameter answers

**Area:** FORMAL (the value model's classification of a parameter, shared by both
backends). Found 2026-10-04 on `work/formal29-3` while re-measuring
`bugs/FORMAL_functools_is_unbuildable_as_a_host_module.md`'s census after the
first-class-function-value capability landed: `functools.reduce(f, seq, init)`
needs `len(seq)`, and that is the refusal that answers it now.

**NOT FIXED. The refusal is honest (nothing wrong is computed) and the
inconsistency is the finding: one parameter, two classifications, and the one
that is refused is the one that works everywhere else in the tree.**

## What was run

```console
$ cat .tmp/lp4.mojo
def at(xs, i):
    return xs[i]

def main():
    printf("a=%d\n", at([1, 2, 3, 4], 2))
    return 0

$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/lp4 .tmp/lp4.mojo
Built: .tmp/lp4  [arm64/macho]
$ ./.tmp/lp4
a=3                      # CPython: 3
```

and the same program with `len`:

```console
$ cat .tmp/lp.mojo
def total(xs):
    var acc = 0
    var i = 0
    while i < len(xs):
        acc = acc + xs[i]
        i = i + 1
    return acc

def main():
    printf("t=%d\n", total([1, 2, 3, 4]))
    return 0

$ … --backend=arm64 …
build: len(xs) is len() of a value classified as 'int', and an integer has no
  length: there is no count to read at offset 0, and the word there is the integer
  itself. A string's length is a strlen over its bytes and a list's is its count
  field, and …
```

Byte-identical on x86-64. **Annotating the parameter does not help**, which is
the part that makes it a shape rather than a missing annotation:

| declaration | `xs[i]` | `len(xs)` |
|---|---|---|
| `def at(xs, i)` | **works** — `a=3`, CPython 3 | refused |
| `def total(xs: List[Int])` | works | **refused** |
| `def count(xs: List[Cell])`, `struct Cell: var v: Int` | works | **refused** |

And a loop that never asks for the count works, because the bound is a literal:

```console
$ cat .tmp/lp5.mojo        # same body, `while i < 4:`
$ ./.tmp/lp5
t=10                      # CPython: 10
```

So the parameter is a blob everywhere except in the one reader that wants its
count field, and the fix is a one-sided divergence rather than a missing
capability.

## Why it is worth its own document

* **It is the blocker for a whole class of host-module functions.** A module
  function that takes a list — `functools.reduce`, `max(xs)`, `sorted(xs, key)`,
  and every helper in this repository's own `formal/hostmods/` that would want
  one — cannot ask how long its argument is. `functools.reduce` is the measured
  instance and `bugs/FORMAL_functools_is_unbuildable_as_a_host_module.md` §"The
  exact next step" now names this instead of the callable argument.
* **The refusal's own sentence is FALSE of this program**, which is the
  expensive kind: *"a value classified as 'int'"* is what the reader is told, and
  `xs[i]` in the same function is answered by the blob path, so the name is not
  an integer. The sentence is true of the CLASSIFICATION and false of the VALUE,
  and the reader who goes looking for an integer in their program will not find
  one.

## The next step

**Find the reader that classifies and ask it the question `xs[i]` is answered
with.** `formal/model.py` has the two answers already: the subscript side goes
through `subscript_base_lowering` / the blob value model (a count field at offset
0 behind a pointer), and `len()` goes through a kind read that reaches
`declared_type_kind`'s scalar answer because a PARAMETER's declared type is
either absent (`List[Int]` does not name a value type on this path) or names an
element rather than the container. So the work is to make the `len` reader ask
"does a SUBSCRIPT of this name lower through the blob path?" — the predicate
already exists and is already right for `xs[i]` — instead of asking what KIND the
parameter is, and to keep the refusal for a parameter that is genuinely a scalar.

`declared_type_kind`'s docstring is where the two answers should be reconciled
rather than a third reader added: a name this path can subscript is not an
integer, whatever its declaration says, and that is the invariant to write down.

**Measured, and it is what makes the direction safe:** the loop with a literal
bound answers CPython's `10`, so the count field is REACHABLE through this
parameter; nothing about the representation is missing. What is missing is one
reader asking one question the other reader already answers.

**Not measured:** whether the same divergence exists for a STRING parameter
(`strlen` takes the pointer, so probably not), for a nested list
(`List[List[Int]]`), or on a parameter whose element type is itself a container.
Those are the shapes to check, not results.