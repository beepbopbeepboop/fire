# TEST: the `module table` group of `test_formal_bracketed_method_field_set.py`
# is red on `master` — and it is the pin for the measurement fourteen comments
# cite

**Area:** tests (FORMAL). **Status: OPEN, measured on `master`, not fixed.**
Found 2026-10-04 while landing the byte-blob element width, by running the
formal suites the byte-blob change touches. **Pre-existing**: 22 PASS / 4 FAIL
with that change fully reverted (`git diff master > patch; git apply -R`,
re-run, re-apply).

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_bracketed_method_field_set.py
bracketed method field set: PASS=22 FAIL=4
  FAIL  a_declared_name_that_is_also_a_method_stays_a_field: deriving the field
        set of a 2-method struct asked struct_receiver_stores 0 times; it is a
        property of the STRUCT, so it is asked once
  FAIL  a_store_in_another_method_keeps_the_name_a_field: … 3-method struct …
  FAIL  a_store_through_this_and_inside_a_nested_def_is_a_field: … 1-method …
  FAIL  chained_augmented_and_tuple_stores_are_all_stores: … 1-method …
```

## Why it matters more than four red cases

**This file is in `test_suite.py`'s `UNREGISTERED` set** — a run of it is
minutes of real compilation, so it is deliberately outside every bucket. So its
four reds are **un-gated and unreported**: nothing in `make gate`, the tally or
the coverage number sees them, which is the shape
`CLAUDE.md` calls out as the worse of the two kinds of red ("a declared red and
an unrun red are different failures").

And this is not an arbitrary file in that set. `bugs/FORMAL_build_cost_2026-
10-03.md` §3.1 is the document that decided a MODULE-level table (`framed`,
`wide`, `one_field_struct_names`) is sound to thread through `_prepare_functions`,
and it says the count is pinned **by a test, not by a timing** — by this file's
`module table` group, which "runs the SAME source twice, with and without eight
padding functions, and asserts that every per-struct ask COUNT is unchanged … and
that every per-struct answer LIST is identical". **That pin is red**, so the
group is not currently asserting the property the document relies on, and the
document's own "fourteen comments in `formal/build.py`, `formal/model.py` and
`test_formal_bracketed_method_field_set.py` cite this doc as the provenance" —
which is the stated reason that document is KEPT rather than deleted — names a
file whose relevant half does not run green.

## What the failure says, and why it is not obviously a stale expectation

The assertion is "asked `struct_receiver_stores` **0** times; it is a property of
the STRUCT, so it is asked once". Zero, not two, and not "asked more than once":
the derivation is not happening **at all** for those four programs, which is the
opposite of the pre-fix shape the pin was written to catch (43508 asks, 1031 of
them one line). Two readings are consistent with the message and they are very
different:

1. the group counts calls through a wrapper the current pipeline no longer
   reaches (a renamed helper, or a counter installed on a symbol the code no
   longer calls) — so the property is untested rather than untrue; or
2. `struct_field_names` really is asking nothing for these structs, because a
   different derivation answers them — which would be the soundness result the
   document wanted, reached by a route the test cannot see.

**Which of the two it is decides whether this is a test fix or a codegen
finding**, and it is a two-minute question: the group is failing on a CALL
COUNT, so printing the call sites of `struct_receiver_stores` for one of the
four programs answers it.

## The exact next step

1. Read the `module table` group's counter installation and print, for
   `a_declared_name_that_is_also_a_method_stays_a_field`'s source, every
   `model.struct_receiver_stores` / `model.struct_field_names` /
   `model.struct_is_one_field` call site with its caller. Zero hits with a live
   counter means reading (1) — find which derivation now answers the field set
   and pin THAT, because the pin's job is "the derivation does not move under
   the loop" and a renamed derivation has the same risk.
2. Re-point the four assertions at it, and keep the COUNT shape: a count that
   scales with the function count is the failure the group exists to catch, and a
   pin that only compares answer LISTS would pass on a per-function derivation.
3. `python3 tools/memslot.py --gb 8 --label t -- python3
   test_formal_bracketed_method_field_set.py` → 26/0, then re-run
   `test_formal_value_model.py` and `test_formal_method_param_field.py`, which are
   the other two places the threaded table is read.

**Not attempted here**, and the reason is worth recording: this is
`bugs/FORMAL_build_cost_2026-10-03.md`'s pin, and that document is closed with
its measurements banked; a worker changing the measurement machinery under a
closed performance document is a different change from one that fixes a stale
expectation, and which of the two this is depends on step 1.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_bracketed_method_field_set.py
$ grep -n "struct_receiver_stores" test_formal_bracketed_method_field_set.py
```