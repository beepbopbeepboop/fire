# RUN: four `test_formal_run.py` failures, none of which is a regression — three are refusal-needle drift and one is a host-import wall

**Area:** `test_formal_run.py`'s build-and-run cases.

**Status: PARTIAL (2026-11-01).** Case 3 fixed; case 1 resolved as "the needle is right" (no code change); case 2 still open, needs a judgement; case 4 out of scope (host-import wall, `bugs/formal/FORMAL_the_host_import_wall_is_at_its_honest_floor.md`).

* **Case 3 (`comptime_binding_with_a_literal_value_still_builds`) — FIXED.** The row's program instantiated a non-generic `Box` with a type bracket, so it refused with the `size_of[type, target]` sentence and its name ("still_builds") could never be observed. The row now uses `var b = Box()`, as its own control comment describes, and pins stdout `3`, exit 0. Measured on both backends: `stdout='3' exit=0`.
* **Case 1 (`deref_refuse_a_binary64_value_store_of_an_integer`) — needle is correct.** The check at `formal/model.py` (`pointer_store_refusal` / the binary64 kind check) draws the value-kind sentence ("would write 0x1, a denormal rather than 1.0") for this program, and the row passes on both architectures. The undeclared-pointee sentence is NOT what this program draws: the `Pointer[Float64]` annotation reaches the check. The earlier "either the annotation is not reaching the check or the two swapped" hypothesis is ruled out by the run.
* **Case 2 (`type_argument_list_on_a_generic_struct_of_this_unit_is_read_as_a_container`) — OPEN.** The row passes pinned to the wide-receiver sentence ("the function which created it…"), which is the frame-escape sentence for a frame value (`s`) in the bracket. The row's name and its own comment ("a FRAME in the bracket … TWO DIFFERENT wrong sentences") disagree about which sentence is right for this subject. Decision needed: either (a) keep the frame-escape sentence and rename the row to a frame-in-bracket name, or (b) rewrite the row to use a non-frame value so the CONTAINER refusal is what it reaches, and pin that. The two spellings must be checked distinguishable before pinning.
* `test_regression_needle_drift.py` was rewritten: it asserted `msg in msg` (tautological). It now runs the named rows through `test_formal_run.py -v` and reads each verdict line. Before the case-3 fix: case 3 FAIL; after: both PASS.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ /opt/local/bin/python3 tools/memslot.py --gb 8 --label run -- \
      /opt/local/bin/python3 test_formal_run.py
formal run: PASS=1326 FAIL=6
```

(the run under `/opt/homebrew/bin/python3` reports `FAIL=20`; fourteen of the
extra fourteen are a CPython-version artefact with its own doc —
the printf-number-conversion check's CPython wording drift.)

Two of the six were fixed on this branch and are not here:

* `a_slice_element_whose_base_builds_a_container_is_refused` → renamed
  `a_slice_element_that_builds_a_container_is_per_iteration`, now pins the
  answer `9 1` instead of a refusal (the construct builds, runs, and is
  per-iteration);
* `comptime_class_attribute_of_a_generic_struct_read_through_its_name` — same
  shape, now pins `3`.

## The four, one at a time

### 1. `deref_refuse_a_binary64_value_store_of_an_integer`

Pins `refuse:would write 0x1, a denormal rather than 1.0` for

    def store(p: Pointer[Float64]) -> Int:
        p.value() = 1

and today refuses with the **undeclared-pointee** sentence ("Declaring the
pointee — a parameter annotated `Pointer[UInt8]`, a local
`var p: Pointer[Int32]`, or a pointer-valued `external_call[…]` — is what makes
it answerable") — which is a DIFFERENT subject: the parameter IS annotated
`Pointer[Float64]`, so either the annotation is not reaching the check or the
two refusals have swapped places. **Resolved (2026-11-01):** the value-kind sentence is the right one; the row was already correct. Until then the row is red for a reason
its needle does not describe, which is the state that is worth not leaving
unexplained.

### 2. `type_argument_list_on_a_generic_struct_of_this_unit_is_read_as_a_container`

Pins `refuse:compile-time explicit-parameter list` for
`Triple[Int, s, False](5)` where `Triple[A, B, C]` has three parameters and the
row's whole subject is that the list is read as a CONTAINER. It refuses with the
**wide-receiver** sentence instead ("…the function which created it, so it can
only be read, written, copied, or passed as a method's receiver", which also
cites `bugs/formal/FORMAL_wide_receiver_by_reference.md`).

**This row's own neighbour says the pin is stale**: the comment immediately below
it records that "`Triple[Int, s, False]` now draws that sentence too, because
the param-independent template is in `structs_by_name`" — i.e. the
explicit-parameter-list refusal is now reachable from a construct that is not the
row's subject, so it can no longer distinguish anything. **Next step:** pin the
CONTAINER refusal the row is named for, and check that the two spellings really
are distinguishable before pinning either.

### 3. `comptime_binding_with_a_literal_value_still_builds`

Refuses with the **absent-capability** sentence ("The word is missing because of
a binding in another module, not because of a capability here. Refused rather
than read as an index — a binding for `size_of[type, target]` would have to come
from a target description this backend does not have, and a plausible constant
is a fabricated answer"). The row's name says "still_builds", so the row is
about the build and the needle is about a refusal — one of the two is wrong.
**Resolved (2026-11-01):** the row now builds and prints `3` (see Status).

### 4. `tag-generator`

Not a case at all — a whole-file check. Its import closure does not resolve:
`collections, contextvars, copy, importlib, keyword`, and the message says so
itself ("every one of those is a `not-answerable/host-import` row in the sweep
and takes this file's 1043 build-and-run rows with it"). This is the documented
host-import wall, not a regression, and it is the same subject as
`bugs/formal/FORMAL_the_host_import_wall_is_at_its_honest_floor.md`. **Next step:** it
is that doc's, and nothing on this branch may change it.

## What is NOT wrong here

The twelve container-refusal rows in the same file and the two
built-where-a-refusal-was-expected rows were all fixed on this branch; see
`99cd6041` and `54da217b`'s neighbours in the history. This doc is the residue
after those, and it is deliberately four separate judgements rather than one
sweeping "update the needles", because **two of these four have a needle that is
wrong about the construct's subject** and only a reading can tell which.