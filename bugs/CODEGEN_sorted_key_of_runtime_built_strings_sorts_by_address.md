# CODEGEN: a `sorted(..., key=)` whose keys are RUNTIME-BUILT strings sorts by pointer address

Found 2026-10-30 while running `test_gimple_runner.py` (the `gimplerunner` row
of the `check` bucket) for unrelated work. It is RED on this tree and was red
before that work: A/B-verified by reverting the whole change under test and
re-running the file — 261 passed / 3 failed with and without, this case among
the three, same output both ways. Not mine; filed here because a red
`check`-bucket row that nobody owns is a hole, and because the fix is in the
area my own change also touched (string comparison through a boxed handle).

## Status: OPEN, pre-existing, reproduced, undiagnosed below the discriminator.**

## What it does

```python
def k3(x):
    return x + "!"

names = ["ccc", "a", "bb"]
print(sorted(names, key=lambda s: k3(s)))
print(sorted(names, key=lambda s: s + "!"))
```

CPython: `['a', 'bb', 'ccc']` twice. Compiled: `['ccc', 'a', 'bb']` then
`['a', 'bb', 'ccc']`.

The first line is the input order, and the input order is what you get from
comparing the key strings as raw `int64_t` POINTERS: three
`mojo_str_cat`-built strings in one arena come out in allocation order, which
for `["ccc", "a", "bb"]` is the reverse of the wanted order. The second line
is right, so the comparator itself works when the key's contents are visible
to it.

This is the case `test_gimple_runner.py` itself was written to be the guard for
— its own comment calls it "a runtime that recognises only one of the two
shapes is the bug both this and the two cases above exist to catch" — so this
is a guard that is doing its job. The three sibling cases
(`gimple_sorted_string_key_not_in_address_order` and the two above it) pass,
which is what makes this one informative: the discriminator handles LITERAL
strings and fails on heap strings.

## What is ruled out

* Not the literal-vs-heap predicate `mojo_boxed_is_str`'s own comment warns
  about. That predicate is deliberately the loose `_mojo_ptr_shaped` range
  test precisely so literals are accepted; a `mojo_str_cat` result is
  pointer-shaped by a wide margin, so it answers "yes, this is a string" and
  the comparator should have taken the string path.
* Not `sorted`'s key plumbing: the key function runs (the keys are real
  strings), and the no-key `sorted(names)` in the neighbouring case is right.

## Next step

The comparator is `_mojo_sort_cmp_at(a, b, kind, depth)` in
`runtime/fire_runtime.c`, and its `MOJO_KIND_STR` arm calls
`_mojo_sorted_str_cmp(a, b)`. So the question is what KIND BYTE reaches it
for these keys:

1. Emit the kind the sort actually used. `mojo_list_sort (l, kind, ...)` takes
   the kind as an argument (`MOJO_KIND_*`, see `runtime/fire_runtime.h:637`),
   and `mojo_boxed_is_str` is the fallback that decides it — so a one-line
   `fprintf (stderr, "sort kind=%c a=%p b=%p\\n", k, ...)` inside
   `MOJO_KIND_STR`'s arm (or just before it) tells you whether the keys reach
   the string arm at all. That is the one measurement that splits the space
   in half, and it is cheaper than any source reading.
2. If the kind is right and the ORDER is still input order, the bug is inside
   `_mojo_sorted_str_cmp` — most likely it is not being reached because the
   sort is picking the `MOJO_KIND_INT` arm from a kind byte computed BEFORE
   the keys are built (the sort is told its element kind by the caller's
   inference, and for a key CALL result there is no such inference).
3. If the kind is `MOJO_KIND_INT` and the addresses are what got compared,
   the fix is to derive the kind from the key at the sort site rather than
   from the list's tracked element type — i.e. `sorted(xs, key=f)` cannot
   know `f`'s return kind statically, so the comparator has to ask the
   discriminator per pair. That is the same "the element type is a property of
   the VALUE, not of the compile-time name" shape as
   `bugs/CODEGEN_list_element_read_defaults_to_str_across_a_call.md`, and
   worth doing in one place if both are open at once.

A regression row already exists and is red; fixing this is what turns it
green, so no new test is needed — only the fix.