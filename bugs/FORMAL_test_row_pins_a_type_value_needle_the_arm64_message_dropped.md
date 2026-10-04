# `a_subscript_on_a_type_value_faulted_identically` is red on master: the arm64 refusal no longer says "is a TYPE value"

**Status: NOT FIXED, and PRE-EXISTING.** Measured on this branch and on
`master` with the three `formal/*_codegen.py` files and the test file restored
from `git show master:…` — identical failure on both trees, so nothing in the
fuzz-5 session's backend changes caused it. Found by running
`test_formal_x86_64_parity.py` in full after landing two x86-64 `del` fixes; it
is the file's only red and it is not one of this session's rows.

## What was run, what was seen

    python3 tools/memslot.py --gb 8 --label par -- \
        python3 test_formal_x86_64_parity.py a_subscript_on_a_type_value_faulted_identically

```
FAIL  a_subscript_on_a_type_value_faulted_identically: --backend=arm64 refused,
but not with the expected words 'is a TYPE value': eading is not merely wrong,
it is unmapped, and no subscript spelling of one means anything else. What the
same source can do instead: index a list or a tuple you built, take the
container as a PARAMETER of main where the caller's value decides, or pass the
value itself to the function that wants it
```

The expectation is a `refuse:` row, so it asserts two things: the build must
fail, and the message must contain `is a TYPE value`. The build DOES fail on
both architectures — the refusal is real and the clause about unmapped memory is
true — and the words are gone. What replaced them is the same refusal with the
"this is a TYPE" clause dropped, so a reader is told the address is unmapped
without being told why the subscript is reading a type tag at all.

## Where the wording lives, and what the fix is

`formal/model.py` owns the sentence (`DType`-as-a-value has its own kind, and
`formal/model.py`'s comment above `BLOB_HEADER_BYTES` is the same file's note
that a type is "a TYPE rather than a value, which is why they are a class of
their own"). Two ways to close it, and the first is the one this repository's
conventions ask for:

1. **Re-word the message to include the clause the expectation names**, keeping
   the existing text. That is what `test_formal_run.py`'s `refuse_without:` rows
   exist to protect against — a fix that APPENDS the true sentence and leaves a
   false one is the failure mode, and here nothing is false, a clause is
   missing — so re-wording rather than replacing is safe and is the smaller
   change.
2. Or re-word the CASE's needle to what the message now says, **only** after
   establishing that the new words are true of every source the row can be given
   — which is the judgement the case's own comment says nobody should make from
   the tail of a diagnostic.

What is NOT the fix: dropping the row, or marking it `expect=`. It is a real
message about a real construct and the case is the only thing that says the
construct is refused identically on both machines.

## Why it is filed here rather than fixed here

It is arm64's refusal wording, in `formal/model.py` and the arm64 emitter's
error path — neither is in the fuzz-5 claim, and the same two files carry this
session's other changes, so a second worker editing them concurrently is the
collision the claims table exists to prevent. The measurement is what was
missing; this is it.
