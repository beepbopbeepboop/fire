# FORMAL_one_word_eq_dispatch_stops_at_a_call_boundary: a ONE-FIELD class's `__eq__` is reached only when the comparison is in the same function that constructs it

**Status: OPEN, not fixed, and NOT a dataclass question — found while fixing
`FORMAL_dataclass_own_eq_is_still_refused_though_dispatch_works.md`, which is
now closed.** Measured on this tree and on its parent (`7c919b11`), both
architectures; the parent measurement is what makes it pre-existing rather than
a regression from that fix.

## What it is

A class of ONE field has no frame on this path: `struct_is_framed` is False,
`P(7)` binds a plain word that IS the field, and the holder tables have nothing
to say about the name. `_rewrite_eq_on_frame_receivers` knows this — it asks
the one-word table (`fn._one_word_candidates`) in exactly the place it asks the
holder table, and `bugs/FORMAL_eq_dispatch_on_a_frame_receiver.md` §1 is the
measurement that it was added for.

What it does NOT do is carry that answer across a CALL BOUNDARY. The one-word
table is seeded from CONSTRUCTIONS in the function's own body, so a parameter
is in it only if some call site in this image hands the parameter a
one-word construction — and the seeding does not reach it:

```python
class Tag:                      # one field, no decorator: this is not a
    v: int                      # dataclass question, it is a struct question
    def __eq__(self, other):
        return True

def eq(a, b):
    if a == b:
        return 1
    return 0

def main(n):
    a = Tag(5)
    b = Tag(6)
    printf("%d %d", eq(a, b), eq(a, a))
```

| | CPython | arm64 | x86-64 |
|---|---|---|---|
| `eq(a, b)` | 1 | **0** | **0** |
| `eq(a, a)` | 1 | 1 | 1 |

The second row is what makes the first a bug rather than a coincidence: the
identity case answers 1 by the ADDRESS compare, which is CPython's INHERITED
`__eq__` — so a program can print `0 1` for a class whose method says True and
read as "it worked".

The same program with the comparison MOVED into `main`, one line above where it
was:

```python
    a = Tag(5); b = Tag(6)
    printf("%d %d", a == b, a == a)      # arm64 1 1, x86-64 1 1
```

dispatches correctly on both architectures, which is the whole of the
diagnosis: the rewrite fires when the operands are names the CURRENT function
bound from a one-word construction, and not when they arrived as PARAMETERS.

## Why it is not a one-line fix

The holder tables' interprocedural edge is seeded from `struct_construction_plan`
for FRAME structs — a by-reference construction `P(3, 4)` in the caller makes
the callee's parameter a holder. The one-word table has no such edge, and
adding one is the same work in a new place: which call site, of how many, with
what argument, and a disagreement between two call sites must leave the name
OUT (the tombstone rule `ValueKinds._ctor_calls` already states for the same
reason). The parameter also has to survive being passed to a SECOND function
(`eq(a, a)` passes `a` twice, and `eq` is the one being asked).

So the next step is "seed the one-word table from the call sites of the
parameter's own function, under the same agreement rule `struct_frame_slot_candidates`
uses for the frame half", and the measurement above is what says the frame half
does not need re-measuring.

## What was done instead, and why it is not in a test

`test_dataclasses_formal.py`'s `a_user_declared_eq_reaches_the_method_on_a_one_field_class`
puts its comparison in `main`, and says so in a comment pointing here. A row
that compared across a boundary would have to assert `0 1` — the expectation
would be a known-wrong answer, and a case whose oracle is a known-wrong answer
teaches the next reader that the wrong answer is the answer.

## Reproducing

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove --backend arm64 \
      -o .tmp/ow1 .tmp/ow1.py && ./.tmp/ow1          # 0 1
$ python3 -c "
class Tag:
    v: int
    def __eq__(self, other): return True
a=Tag(5); b=Tag(6); print(a==b, a==a)"               # 1 1
```
