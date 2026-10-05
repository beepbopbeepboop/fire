# TEST: `a_subscript_on_a_type_value_faulted_identically` pins a needle the FIELD arm of the message never says

**Area:** tests (`test_formal_x86_64_parity.py`, the arm64/x86-64 refusal-parity
corpus). **Status: OPEN, measured, pre-existing on `master` (4eca3e65), not
fixed.** Found 2026-10-04 while merging `work/formal23-2` and
`work/formal23-3` into `work/merge-formal23` and running the parity corpus. It
is NOT caused by that merge: a pristine archive of `master`'s HEAD reproduces it
identically (§"What I saw", third command).

Re-measured 2026-10-04 again, on the tree that had `work/formal26-fuzz-5`'s
x86-64 `del` and dict-walk fixes in it (`PASS=77 FAIL=1 (78 cases)`, same single
row, same words) — so it survives the fuzz-5 session's backend changes too, and
`work/formal26-fuzz-5` filed its own doc for the same red, which this one
supersedes: its two proposed fixes are the two below, and the first is the one
this file's "exact next step" already names.

Re-measured a third time on the five-branch merge (`work/merge-formal27a-r2`):
`PASS=77 FAIL=1 (78 cases)`, the same single row and the same words, and
**proved pre-existing on a pristine `git archive master` run of the row alone**
(`PASS=0 FAIL=1 (1 case)`) rather than by reasoning about the diff. A third doc
covers this row — `work/formal25-1`'s, which is the one that names the MECHANISM
(why the one-field rewrite used to fold `s.d` onto its receiver, and the
`__init__` that stops the fold, which is why the base reaching the gate is a
`MemberExpr` and not a bare name) and warns against answering it with an
`expect=`. Three docs for one red is two too many; this one is kept because it is
the only one of the three that shows the family table and so says whether the
row is still a distinct case at all.

`test_formal_x86_64_parity.py` is not in `tools/suite.py`'s registry — there is
no job naming it — but it IS declared in `test_suite.py`'s `UNREGISTERED` as
`test_formal_x86_64_parity.py: _FORMAL_SUITE_REASON`, so the estate check counts
it. **This file's earlier claim that it was in neither was wrong**, and the
correction matters rather than being bookkeeping: an entry in `UNREGISTERED` is a
statement that the file is red today and no gate reports it, which is exactly
what this row is, and the count in that block is a re-run of every entry rather
than a reading of a doc. What is still true is the consequence — a declared red
in a bucket nobody runs is invisible to every gate, so nothing observes this row
going green, and nothing observes it going red a second time.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label par -- python3 test_formal_x86_64_parity.py
  ...
  x86-64 formal parity: PASS=67 FAIL=1 (68 cases)

# and, to attribute it, on a pristine copy of master rather than on the merge:
$ mkdir -p .tmp/head_tree && git archive HEAD | tar -x -C .tmp/head_tree
$ (cd .tmp/head_tree && python3 test_formal_x86_64_parity.py)
  ...
  x86-64 formal parity: PASS=62 FAIL=1 (63 cases)      # same single row
```

## What I saw

```
FAIL  a_subscript_on_a_type_value_faulted_identically: --backend=arm64 refused,
but not with the expected words 'is a TYPE value': eading is not merely wrong,
it is unmapped, and no subscript spelling of one means anything else. What the
same source can do instead: index a list or a tuple you built, take the container
as a PARAMETER of main where the caller's value decides, or pass the value
itself to the function that wants it
```

The refusal is CORRECT and it is the one this tree wants — `model`'s
`scalar_container_base_refusal`, both backends, no SIGSEGV. The needle is wrong.

**Which arm the message takes, and why that is the whole of it.**
`formal/model.py::scalar_container_base_evidence` has two `TYPE_KIND` arms and
they are different sentences:

| the base | the arm | the words |
|---|---|---|
| a bare name, a call, a literal — anything that is not a FIELD | the second | `a TYPE value — the tag word this path gives a type name …` |
| a `MemberExpr` | the first | `a struct field declared to hold a TYPE TAG — a hash of a type's name — which is a number …` |

The row's base is `s.d` — a `MemberExpr` — so it takes the field arm, and
`"is a TYPE value"` is a phrase the field arm does not contain anywhere. The
needle was taken from the non-field arm, which is the one a reader would reach
for having tested `5[0]` and never a field.

## Why the family is still covered, and what is actually duplicated

The three-row table above is not a coverage hole: two sibling rows pass and pin
the FIELD arm's own words, and one of them is the SAME SOURCE.

| row | base | needle | |
|---|---|---|---|
| `subscript_of_a_slot_declared_an_int_refused_identically` | `s.n` | `a subscript of \`s.n\` asks for a container element` | PASS |
| `subscript_of_a_dtype_slot_refused_identically` | `s.d`, class default | the kind clause | PASS |
| `subscript_of_a_constructor_established_dtype_slot_refused_identically` | `s.d`, set by `__init__` | `is a struct field declared to hold a TYPE TAG` | PASS |
| `a_subscript_on_a_type_value_faulted_identically` | `s.d`, set by `__init__` | `is a TYPE value` | **FAIL** |

The last two differ only in that the failing row's `struct S` declares one field
where the passing one declares two (`var t: Int`, unused). So the exact next step
is not just a re-point: it is re-point **and** a decision about whether the row
is still a distinct case at all, because on the evidence above it is the same
program with one fewer unused field.

## The exact next step

1. Re-point the needle at the field arm — `"is a struct field declared to hold a
   TYPE TAG"`, which is what the sibling row two entries up already pins — or
   delete the row and let `subscript_of_a_constructor_established_dtype_slot_
   refused_identically` be the case. The first keeps a row whose struct declares
   only `d`; the second removes a duplicate.
2. If the row is kept, its comment above it (lines 1698-1701: "The `DType` row,
   and the one that faulted on BOTH machines") should say which arm it pins and
   why the row next to it pins a different sentence for the same construct —
   otherwise the next reader re-derives this.
3. The row's real subject — the source that used to SIGSEGV on both machines, and
   the preimage in `scalar_container_base_refusal`'s own table (commit
   `ba63213c`, which renamed the reader and added this row in one commit) — is
   worth a non-field case of its own: a bare `DType` name subscripted, which is
   the arm that arm for. Nothing in the corpus covers it today.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label par -- python3 test_formal_x86_64_parity.py
```