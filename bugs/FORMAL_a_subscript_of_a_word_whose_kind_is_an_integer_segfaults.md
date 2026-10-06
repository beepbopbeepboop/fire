# FORMAL: a subscript of a value whose kind is a KNOWN integer SIGSEGVs, where the same subscript of a literal integer is refused

**Area:** FORMAL (the value model's subscript kind rule — the one `len()`
consults — and the two emitters' element-address path). Found 2026-10-05 on
`work/formal40-1-r2` while fixing
`FORMAL_a_comprehension_element_container_aliases_every_iteration.md`.

**Status: NOT FIXED, and the refusal for this exact program EXISTS on this tree
— it is simply not reached.** Not mine: the doc whose next step is the element
kind of a list subscript (`FORMAL_len_of_a_subscript_of_a_list_of_lists_is_an_
int.md`) is a different gap, and the fix belongs to whoever takes the subscript
kind rule. This document exists because the symptom is a **fault with no
diagnostic**, which is a different class from that doc's refusal, and because
its §"What is not this" was measured rather than assumed.

## What was run, what was seen, what was expected

```console
$ cat .tmp/ce/kk4.mojo
def main():
    v = [1]
    s = v[0][0]
    print(s)
    return 0
main()
$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/ce/kk4.bin .tmp/ce/kk4.mojo
Built: .tmp/ce/kk4.bin  [arm64/macho]
$ .tmp/ce/kk4.bin ; echo "rc=$?"
Segmentation fault: 11
rc=139
```

| | answer |
|---|---|
| CPython | `TypeError: 'int' object is not subscriptable`, exit 1 |
| arm64 | **SIGSEGV**, exit 139, nothing on stderr |
| x86-64 | **SIGSEGV**, exit 139, nothing on stderr |

## The refusal for this program exists, one line away

```console
$ cat .tmp/ce/x.mojo
def main():
    x = 1
    print(x[0])
    return 0
main()
$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/ce/x.bin .tmp/ce/x.mojo
build: … `x[0]` is a subscript of a value classified as 'int' …
```

**That is the whole finding**: the rule that refuses a subscript of an integer
is present and correct, and `v[0]` — whose kind is *also* `int`, and is knowable
without inference because `[1]`'s elements are literals — does not reach it.
So this is not a missing capability; it is a kind that is not carried from the
subscript into the subscript. That is why it faults rather than refuses: the
emitter asked for an element address on a word that is the integer 1, and
`[1 + 0]` is a load from address 1.

## What is NOT this, measured

* **Not the list-of-lists kind gap.**
  `bugs/FORMAL_len_of_a_subscript_of_a_list_of_lists_is_an_int.md` is about
  `len()` of `rows[0]` being refused with a false "'int'" sentence. The ELEMENT
  read through the same subscript is fine there, and here:
  `rows = [[1, 2], [3, 4]]; s = s + rows[0][1]` answers `4` on CPython, arm64
  and x86-64. So the nested subscript lowers correctly whenever the inner
  subscript's base really is a list.
* **Not the aliasing fix next door.** The reproducer above does not involve a
  comprehension at all: it is one subscript of a one-element list literal.
* **Not arm64-specific or x86-64-specific.** Both fault, identically.

## Why it is worth a document rather than a note

The whole formal path's discipline is "a construct with no representation is
REFUSED, never emitted" — `bugs/FORMAL_known_limits.md`'s standing rule, and the
reason a hundred refusal messages exist. This is the shape that rule exists to
prevent and the one failure it cannot produce: the refusal is written, and the
program does not get it. A silent `SIGSEGV` in a corpus of 738 files is the
outcome the sweep's `backend-crash` class is for, and it is 0 files today.

It is also reachable from ordinary code rather than from a fuzzer: it needs a
subscript whose base is an integer, which is one indexing mistake away in any
program that walks a ragged table.

## The exact next step

The SUBSCRIPT's element-kind rule, in `formal/model.py` — the same place
`FORMAL_len_of_a_subscript_of_a_list_of_lists_is_an_int.md` §"The exact next
step" points at, and the two are one edit if it is made as "the kind of
`e[i]` is the kind of `e`'s element, and when that is a known non-container the
subscript is refused by the existing rule". Ask it of a `SubscriptExpr` whose
BASE is itself a `SubscriptExpr` first, because that is the shape that faults,
and `ValueKinds` has the base's kind in hand at that point.

The regression net belongs in `test_formal_value_model.py`'s `REFUSALS`, whose
rows already pin refusal messages by needle, and the needle for it is the
sentence the one-line-literal program above already produces — so a fix that
reaches the rule from the other direction cannot pass by refusing something
else.

**Do not add a `KNOWN_DIVERGENCES` row to `tools/formal_fuzz.py`.** The corpus
deliberately reads nested subscripts through a local (see that other doc's
§"Why the corpus does not generate it"), and this shape is a *crash*, not a
wrong answer: a divergence row would record the fault as an accepted answer,
which is the opposite of what it is.