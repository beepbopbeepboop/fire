# A stale needle, second instance: `a_subscript_on_a_type_value_faulted_identically` expects "is a TYPE value" and gets a different refusal

**Area:** TEST (a test row asserting a diagnostic the tree does not produce at
that site). Found 2026-10-04 on `work/formal26-float` while running
`test_formal_x86_64_parity.py` as a regression check for the binary64 work.
**NOT FIXED, and not mine** — the construct is a subscript on a `DType` value and
it belongs with `formal/model.py`'s subscript refusals, outside the
`project26:float` claim. Filed for the same reason as
`bugs/TEST_stale_needle_on_the_undeclared_base_refusal.md`: two suites' worth of
pre-existing reds found in one session, neither caused by the change, and a reader
who hits them should not have to re-derive that.

## What was run

```
$ python3 test_formal_x86_64_parity.py
…
  FAIL  a_subscript_on_a_type_value_faulted_identically: --backend=arm64 refused,
        but not with the expected words 'is a TYPE value': eading is not merely
        wrong, it is unmapped, and no subscript spelling of one means anything
        else. What the same source can do instead: index a list or a tuple you
        built, take the container as a PARAMETER of main where the caller's value
        decides, or pass the value itself to the function that wants it

x86-64 formal parity: PASS=62 FAIL=1 (63 cases)
```

## Why this is not the binary64 change

Measured the same way as the other one: `formal/model.py`, `formal/types.py`,
`formal/arm64_codegen.py` and `formal/x86_64_codegen.py` — the whole write set of
the float change — were restored from the commit before it and the single case was
re-run.

```
$ python3 test_formal_x86_64_parity.py a_subscript_on_a_type_value_faulted_identically
  FAIL  a_subscript_on_a_type_value_faulted_identically: … (identical)
x86-64 formal parity: PASS=0 FAIL=1 (1 case)
```

Byte-for-byte the same failure, so the row is red on the tree the float work
started from. Both of this session's reds are in test files whose needle was
written against an earlier diagnostic.

## What it actually is

The row expects the refusal `formal/model.py`'s subscript machinery produces for a
`TYPE_KIND` base — "… is a TYPE value" — and gets a refusal from a LATER gate in
the same walk. The tail the run shows ("What the same source can do instead: index
a list or a tuple you built, take the container as a PARAMETER of main …") is
advice text, and the sentence before it begins mid-word ("eading is not merely
wrong"), which is the tail of a longer diagnostic whose HEAD is not the one the row
pins.

Two refusals can be right about the same program, and the row was written against
the earlier one. The likely reason a later gate wins now is that the earlier one is
reached only once the base's kind is `TYPE_KIND`, and the base in this program's
source reaches it by a route that no longer answers `TYPE_KIND` at that point —
which is worth checking before assuming the needle simply moved.

## The exact next step

Print the full diagnostic for the case's source (`python3 fire.py build --formal
--no-prove --backend=arm64` on the row's program, not the truncated
`text.strip()[-300:]` the runner shows) and decide which of the two the row means:

- **If the `TYPE_KIND` refusal is still correct and reachable**, the row's PROGRAM
  stopped establishing a type kind — that is a real regression in the kind table
  and the bug doc belongs to whichever change caused it. Check
  `ValueKinds.kind_of`'s `type_value_tag` arm and the `TYPE_KIND` binding for a
  name assigned from `DType.<member>`.
- **If the later gate is the honest one**, move the needle to its text and note in
  the row that the earlier refusal is covered by another row.

The first is the one to check first: this suite exists to catch the two backends
DISAGREEING, and a row that has quietly stopped testing the `TYPE_KIND` path is
the same class of loss as a deleted case — the suite would still be green about a
subscript of a type while no row looked at it.

Note that this row is a `refuse:` row in a parity suite, so it is checked on both
architectures and the failure above is arm64's half; x86-64's half needs looking at
too before the needle is moved, because the whole point of the suite is that the
two can differ.