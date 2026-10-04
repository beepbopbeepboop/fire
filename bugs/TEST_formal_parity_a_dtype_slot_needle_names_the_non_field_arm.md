# TEST_formal_parity_a_dtype_slot_needle_names_the_non_field_arm: `a_subscript_on_a_type_value_faulted_identically` expects `is a TYPE value` and gets the TYPE TAG arm

**Area:** `test_formal_x86_64_parity.py`'s `REFUSALS`, one row. Found 2026-10-04
on `work/formal25-1`. **Pre-existing on master**, proved by running the row out
of a `git archive master` tree rather than by reasoning about the diff.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_x86_64_parity.py a_subscript_on_a_type_value_faulted_identically
  FAIL  a_subscript_on_a_type_value_faulted_identically: --backend=arm64 refused,
        but not with the expected words 'is a TYPE value': …
x86-64 formal parity: PASS=0 FAIL=1 (1 case)
```

and the program it builds, on both architectures, by hand:

```mojo
struct S:
    var d: DType = 5
    def __init__(out self, v: DType):
        self.d = v

def main() -> Int:
    var s = S(DType.int32)
    printf("%d", s.d[0])
    return 0
```

```
build: a subscript of `s.d` asks for a container element, and `s.d` is a struct
field declared to hold a TYPE TAG — a hash of a type's name — which is a
number, and a tag has no elements and no count. …
```

## What I saw

**The refusal is right; the needle names the wrong arm of it.**
`formal/model.py::scalar_container_base_evidence` has TWO rows for a type:

* `field` → `"a struct field declared to hold a TYPE TAG — …"`, and
* not a field → `"a TYPE value — the tag word this path gives a type name, …"`.

This program reaches the first, and the row expects the second. So the row was
written against a version of the lowering in which `s.d` had already been
rewritten — `_rewrite_self_fields` collapses a ONE-FIELD struct's sole field onto
its receiver, and the receiver then folds to the field's materialized default, so
the node the emitter was handed was a bare name and not a MemberExpr. That fold
is exactly what `scalar_container_base_evidence`'s own docstring names for the
scalar-literal arm ("a one-field struct's sole field collapses onto its
receiver").

**What stopped the fold is the `__init__`.** A field with no constructor store
folds to its class-level default, and `5` is a literal, so the emitter sees `5`.
This program has `def __init__(out self, v: DType): self.d = v`, so the slot's
value is whatever the constructor was handed and nothing folds — which is also
what the row's own comment says ("the field is established by the CONSTRUCTOR
rather than by a class-level default, so nothing folds to a literal and nothing
refuses"). **The comment describes the fold and the needle is on the other side
of it.** With no fold, the node reaching the gate is `s.d`, and `s.d` IS a
field.

The row it should look like already exists and passes: `subscript_of_a_
constructor_established_dtype_slot_refused_identically`, three rows further
down, with the needle `is a struct field declared to hold a TYPE TAG` — the same
program. So the file asserts both answers for one construct, one of which the
backend does not produce.

## Why it is pre-existing

`git archive master` into a scratch tree and run the row there, which removes
this branch's diff from the question entirely:

```console
$ rm -rf .tmp/master && mkdir -p .tmp/master && git archive master | tar -x -C .tmp/master
$ cd .tmp/master && python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_x86_64_parity.py a_subscript_on_a_type_value_faulted_identically
  FAIL  a_subscript_on_a_type_value_faulted_identically: --backend=arm64 refused,
        but not with the expected words 'is a TYPE value': …
x86-64 formal parity: PASS=0 FAIL=1 (1 case)
```

## The next step

One line, and the choice is which of the two rows goes:

* **Repoint the needle at the arm that fires** — `"is a struct field declared to hold a TYPE TAG"` — and note in the comment that the constructor-established slot does NOT fold, so the base is still `s.d` when the gate sees it. This is what the sibling row 30 lines below already asserts, which makes the two rows one row; or
* **give it a program that still folds**, by dropping the `__init__` and writing `var d: DType = 5` — but that is then `subscript_of_a_dtype_slot_refused_identically` verbatim, so the row earns nothing the one below does not.

The first is the answer. Do **not** add the row to an `expect=` list: the
refusal is emitted and correct, so the row is stale, not failing — and a marker
there would forgive the NEXT message change on this construct, which is the one
thing this file's needle is there to catch.