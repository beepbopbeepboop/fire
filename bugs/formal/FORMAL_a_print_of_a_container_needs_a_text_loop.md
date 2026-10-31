# `print(<a container>)` is refused: rendering one is a loop emitting text, and `_print_call` builds ONE format

**Area:** FORMAL, both backends — the refusal is
`formal/model.py::container_print_refusal`, asked from
`model.print_call_spelling`, which both `_print_call`s now delegate to.
**Status:** OPEN, measured 2026-10-05 on `work/formal65-format-and-repr` at
`108392fc` (this repository, `/opt/homebrew/bin/python3` 3.14.7, formal arm64 +
x86-64, every row built and RUN on both).

## What I ran, what I saw, what I expected

```console
$ printf 'print([1, 2])\n' > .tmp/l.py
$ for a in arm64 x86_64; do python3 fire.py build --formal --no-prove \
      --backend=$a -o .tmp/l.$a .tmp/l.py; done
build: print() of a container is refused on the formal arm64 path (this operand
is a ListExpr, of kind 'list:int'): …
$ python3 .tmp/l.py
[1, 2]
```

Five spellings, all refused on both architectures with the same message modulo
the syntax node and the kind:

| source | this path, both arches | CPython |
|---|---|---|
| `print([1, 2])` | refused, kind `list:int` | `[1, 2]` |
| `print((1, 2))` | refused, kind `list:int` | `(1, 2)` |
| `print({1: 2})` | refused, kind `list:int` | `{1: 2}` |
| `print({1, 2})` | refused, kind `list:int` | `{1, 2}` |
| `xs = [1, 2]` then `print(xs)` | refused, kind `list:int` | `[1, 2]` |
| `print([[1], [2]])` | refused, kind `list:list:int` | `[[1], [2]]` |

## What landed, and what it changed

The refusal used to be the GENERIC one — `print() cannot tell whether ListExpr
is a string or a number … guessing would print an address as if it were text` —
which was **false about the source**: the model classifies that operand as
`list:int` (`ValueKinds.kind_of`, which reads the literal's element kinds), the
model knows it is a container, and the message told the reader to annotate a
literal that needs no annotation. `container_print_refusal` names the kind, the
syntax node, what CPython prints and what is missing, and
`model.is_container_kind` is the one predicate that decides it (a
`LIST_PREFIX`-prefixed kind or `FRAME_KIND`, so a `bytearray` blob and a frame
address join without a second comparison at the call site).

The rows are `test_formal_format_conformance.py`'s `list_refused`,
`tuple_refused`, `dict_refused`, `set_refused`, `list_name_refused` and
`nested_list_refused`, on both backends.

## Why it is still refused — the actual absence

`print`'s whole implementation is `_print_call` → `print_call_spelling` →
**one** `M.print_format(fragments, sep, end)` string, emitted as a single
`printf`. Every conversion in it is decided at BUILD time from what an operand
statically is. A container is the one operand whose rendering is a function of a
COUNT this build does not know, so rendering it is not a conversion of a word but
a sequence of conversions — `[`, element, `, `, element, `]`.

**The next step is concrete and does NOT need a text buffer**, which is the
useful part of this doc: the emitters can already emit a LOOP and can already
emit one `printf` per element, so `print(xs)` over a blob lowers as

```
printf("[")
for i in 0 .. count:      # count is at base+0, elements at base+8+8i
    if i > 0: printf(", ")
    <the existing per-operand rule for element i>      # %lld / %llu / %s / the
                                                           # bool ternary
printf("]\n")
```

— no buffer, no `strcat`, nothing that `bugs/formal/FORMAL_string_composition_has_no_
buffer.md` is about. Three things have to be decided before that is code, and
each is a question rather than a mechanism:

1. **the bracket pair and the separator per kind** — `[`/`]` for a list and a
   set, `(`/`)` for a tuple, `{`/`}` for a dict, and CPython's dict spelling is
   `{'a': 1}` (key, `: `, value) rather than a plain separator. `ValueKinds`
   already answers dict-vs-list (`is_dict_value`, `_dict_names`), so the
   brackets are a table over what it returns.
2. **the ELEMENT's own rendering** — an element is a word whose kind comes from
   `list_elem_kind`, so `list:int` gives `%lld` and `list:str` gives `%s`, both
   of which exist. A container of containers recurses, which is the part that
   makes this a loop nest rather than a loop.
3. **the empty case** — `print([])` is `[]` and `print({})` is `{}`, so the loop
   must be over `count` and the brackets unconditional. That is the row that
   catches an implementation that emits the separator before the first element.

**What is NOT the fix**, and is named because it is the obvious one:
`printf("%s", xs)` on a blob prints the ADDRESS (that is
`FORMAL printf d of a container prints its address`'s measured shape,
and `string_operand_is_string` is what admits it), and a `%s` cannot render a
`[` or a count.

## Also still wrong on this path, and measured here

Two renderings a reader will hit while looking at this one, both of which are
`print` of a runtime word where CPython writes a NAME:

* `print(int)` prints the type's TAG as a decimal (`3143511548502526014`) where
  CPython prints `<class 'int'>` — **deliberate**,
  `formal/model.py`'s `TYPE_KIND` says a tag is a word and `is_number_kind` says
  a word prints as a number, and `test_formal_run.py`'s
  `TYPE_VALUE_NUMBER_CASES` pins the tag. Pinned here as
  `type_value` in `DIVERGENT_ROWS`.
* `print(p)` for a class instance prints the instance's one word (`1` for a
  one-field struct, where the word IS the field) where CPython prints
  `<__main__.P object at 0x…>`. Pinned as `instance`.

Both are in the same place in the reader's head — "what does this path write for
a value that is not a number?" — and neither is fixed by the loop above.