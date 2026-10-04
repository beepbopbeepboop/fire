# TEST: `a_subscript_on_a_type_value_faulted_identically` asserts a message this backend stopped saying

**Area:** the test suite's own needle — `test_formal_x86_64_parity.py`, one row.
**Status:** OPEN, measured 2026-10-04 on `work/formal26-unicode` at `674e8f11`.
Pre-existing on that branch's base; **NOT caused by the string/unicode work on
the same branch** (the measurement that proves it is in §2).

## 1. What was run

```console
$ python3 test_formal_x86_64_parity.py
  FAIL  a_subscript_on_a_type_value_faulted_identically: --backend=arm64
        refused, but not with the expected words 'is a TYPE value': … a tag has
        no elements and no count. …
x86-64 formal parity: PASS=62 FAIL=1 (63 cases)

$ python3 fire.py build --formal --no-prove --backend=arm64 -o tv.bin tv.mojo
build: a subscript of `s.d` asks for a container element, and `s.d` is a struct
field declared to hold a TYPE TAG — a hash of a type's name — which is a number,
and a tag has no elements and no count. …
```

## 2. It is the NEEDLE that is stale, not the compiler

**The refusal is correct, identical on both machines, and its wording is the one
two sibling rows already assert.** The three `DType` cases in that table:

| row | its needle | verdict |
|---|---|---|
| `subscript_of_a_dtype_slot_refused_identically` | `is a struct field declared to hold a TYPE TAG` | PASS |
| `subscript_of_a_constructor_established_dtype_slot_refused_identically` | `is a struct field declared to hold a TYPE TAG` | PASS |
| `a_subscript_on_a_type_value_faulted_identically` | `is a TYPE value` | **FAIL** |

The three programs differ in ONE thing — how the field is established — and the
three rows were written to hold that difference down, so they should agree on the
message and two of them do. The third kept an earlier wording. Its own comment
still describes the defect it was created for accurately ("the field is
established by the CONSTRUCTOR rather than by a class-level default, so nothing
folds to a literal and nothing refuses"), so the row still tests what it says it
tests; only the words it greps for are from before the message was reworded.

**Not a regression from the branch it was found on.** Measured by neutering the
branch's only per-build addition — `formal/build.py`'s
`M.publish_non_ascii_strings(M.non_ascii_strings_in(stmts))`, replaced with
`M.publish_non_ascii_strings([])` and then restored:

```console
$ python3 test_formal_x86_64_parity.py a_subscript_on_a_type_value_faulted_identically
  FAIL  a_subscript_on_a_type_value_faulted_identically: … same message …
x86-64 formal parity: PASS=0 FAIL=1 (1 case)
```

Same failure with the string-encoding work switched off, and the program in
question contains no non-ASCII text, so it could not have reached the encoding
block's condition in the first place.

## 3. The next step

**One string.** Change the needle `'is a TYPE value'` to the wording its two
siblings assert — `'is a struct field declared to hold a TYPE TAG'` — and the
table is green with the coverage it was written for.

**Worth saying rather than leaving implicit:** a refusal needle is a CONTRACT,
and a reworded message silently invalidates it in the one place where the
reword cannot be noticed by reading the program. Two things would have caught
this and neither is in place — a needle set shared between the sibling rows
rather than spelled three times, and a check that every needle in the file is a
substring of some message the tree actually produces. The first is a two-line
refactor of this table; the second is what `test_formal_doc_truth.py` does for
the documents and has no equivalent here.