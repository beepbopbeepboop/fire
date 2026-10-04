# `test_dataclasses_formal.py`'s `post_init` expectation names wording the
# compiler stopped producing in `50661cc0`

**Area:** FORMAL, tests only — `test_dataclasses_formal.py:909` against
`formal/model.py::one_field_dropped_receiver_stores`.

Found 2026-10-03 on `work/formal18-1` while running the suites that cover
`bugs/FORMAL_a_function_whose_return_value_is_a_construction_is_not_frame_
returning.md`. It is pre-existing on `master` and is not that change's: it
reproduces with `formal/build.py` at HEAD byte for byte (measured by writing
HEAD's copy of the file over the edited one, running the single case, and
restoring — never `git checkout <path>`).

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_dataclasses_formal.py post_init_is_refused_with_its_reason
FAIL: post_init_is_refused_with_its_reason: the refusal does not say what it
should: missing 'no point in that sequence' — got: compute the new value and
drop it, and the object the caller holds would keep the old one. Declare the
receiver `out self` (or `inout self` / `mut self`) so it is handed back, or
split the method into one that changes the receiver and returns nothing and
one that reads it. (The rule is `formal/model.py`'s
`one_field_dropped_receiver_stores`; `receiver_writeback_name` is the
mechanism it is about.)

1 passed, 1 failed
```

## What I see

The case's needle is `"no point in that sequence"`, a phrase
`formal/model.py` does not contain at all on this tree
(`grep -rn "no point in that sequence" --include=*.py .` returns only the
test). The message the build actually produces is the **one-field dropped
receiver store** refusal, which is a different and *more specific* diagnostic:
it says the `__post_init__`'s `self.f = v` write is computed and thrown away
and names the convention that would fix it.

So the case is red for a reason that is not a compiler bug: the refusal
`POST_INIT` used to raise is now pre-empted by the receiver-store rule, and
the needle was not updated with it. `50661cc0` ("formal: @dataclass as a
compile-time transform, not a runtime module") is the commit that introduced
`one_field_dropped_receiver_stores`.

## Why it is worth a doc rather than a deleted expectation

`POST_INIT` is still refused — the suite proves that (the case fails only on
the WORDING) — so deleting the expectation would assert something weaker than
what the tree does. Two ways to close it and they are not equivalent:

1. **The case should accept either message.** A `__post_init__` on a one-field
   class is refused by BOTH rules, and which one is reached first is a
   property of the receiver convention the case spells rather than of
   `__post_init__`. So the assertion ought to be "refused, and the sentence
   says why the write does not survive" — a needle that both messages
   satisfy (`does not reach the caller` / `keep the old one`), plus a second
   case with a MULTI-FIELD class, where the dropped-store rule cannot fire and
   the `__post_init__` sentence is the only one left. That second case is the
   one that actually pins `__post_init__`.
2. **Reorder the two refusals** so the `__post_init__`-specific sentence wins
   for a `__post_init__`. That is a change to which check runs first, in
   `formal/model.py` / `formal/dataclass_transform.py`, and it makes the more
   specific message the one a reader of a `__post_init__` error sees.

Option 1 is the smaller change and the one that matches the tree's discipline
of asserting a sentence rather than a fact; option 2 is the better diagnostic.
Either way the `__post_init__` rule needs a case of its own that the
receiver-store rule cannot pre-empt, and that is the part of this that is
currently untested.

## The exact next step

Pick option 1 or 2, and in either case add the multi-field `POST_INIT` case.
Verify with

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_dataclasses_formal.py
```
