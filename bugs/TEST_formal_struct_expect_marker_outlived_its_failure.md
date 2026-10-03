# TEST: `formal-struct` is `expect=`-marked for a failure the test no longer has — the anti-rot is red in `proofs` and the coverage it was watching is gone

Found 2026-10-01 while giving the eleven ungated `expect=` tests a bucket
(`bugs/TEST_expect_marked_tests_in_no_bucket_never_run.md`, now deleted with
its fix). The marker-undercount work made me run every `expect=`-marked test,
and this one does not fail.

## What I ran, and what it said

    $ python3 tools/memslot.py --gb 8 --label formal-struct -- \
          python3 tools/suite.py formal-struct
    ...
      ok       formal-struct                                    80.3s peak 0.1 GB
      FAIL     formal-struct  (marked expect='bugs/FORMAL_struct_pack_over_
                  eight_arguments.md — …' but it PASSES — drop the marker
                  and fix whatever it was waiting for)
    suite: 1 passed, 1 failed, 0 skipped, 0 expected-failure  (2 tests, 2 jobs)

and the test on its own:

    $ python3 test_struct_formal.py ; echo $?
    148/148 checks passed
    0

`bugs/FORMAL_struct_pack_over_eight_arguments.md` says, in its Status,
"**2 of 148 checks fail, on arm64.**" Both were
`test_unservable_formats_are_refused_not_wrong` on the two 8-value formats:
the test built `pack("<IIQQQQQQ", …)` with all eight values, the call is nine
arguments wide, and `formal/arm64_codegen.py:6140` refuses it
(`call {name}(): {nargs} arguments exceeds the 8 the formal arm64 ABI passes
in registers`) — so the module's own in-band "return an empty list" decline
was unreachable and the group saw a build failure where it wanted a `0`.

## What actually changed, and why that is not a fix

The refusal is still there. What changed is the fixture, in
`test_struct_formal.py:580`:

    values = [1] * len(struct.unpack(fmt, bytes(struct.calcsize(fmt))))
    values = list(values[:5])          # ← new
    …
    while len(values) < 5:
        args += ", 0"

`values` is now truncated to five before the call is built, so the widest
corpus format no longer produces a nine-argument call. The comment above it
explains the intent — "A format with more values than that is the case under
test, so the call must not simply hand it every value … padding to five says
exactly the intended thing: five values supplied, more wanted" — and for the
module's *behaviour* that is true and reasonable. For the bug the doc is about
it is not: the emitter's arity ceiling is no longer exercised by this test at
all, and `formal/arm64_codegen.py:6140` is the code that would break silently
if it stopped refusing (its own comment records what the alternative built:
the ninth parameter read as ZERO).

So this is not "the bug got fixed, delete the doc". It is the marker meeting
the one thing markers are for: the test changed shape, the failure went away,
and the anti-rot said so.

## Why it is filed here and not fixed here

`bugs/FORMAL_struct_pack_over_eight_arguments.md` is another claim's, and so
are `formal/arm64_codegen.py` and `test_struct_formal.py` as far as I can
tell. Both halves of the decision — drop the marker, or put the 8-value arity
back into the fixture — belong to whoever owns them, and they are different
decisions with different consequences.

Note the shape, because it is the one CLAUDE.md's anti-rot rule is about: a
`expect=` marker is a claim about a test, and here the claim stopped being
true for a reason nobody wrote down. `bugs/TEST_expect_marker_undercounts_the_
failures_it_absorbs.md` (deleted with its fix) was the other direction of the
same drift — a marker that absorbed a failure it did not describe.

## Exact next step

1. Decide whether the 8-value arity is still a case this tree wants watched.
   The test's own `UNSERVABLE` list still names `<IIQQQQQQ` and
   `<4sBBBBBBB5x`, and `test_the_unservable_list_is_exactly_the_wide_pack_`
   `formats` still asserts the list is the wide ones, so the INTENTION is
   still there — only the construction stopped reaching the ceiling.
2. If yes: build one of those two formats with all eight values, assert the
   call-site refusal *by name* (`exceeds the 8 the formal arm64 ABI passes in
   registers`) and drop the empty-list assertion for it. That is the doc's own
   "option 2", and it is a smaller `struct.pack` than
   `formal/hostmods/struct.mojo` documents — so its docstring has to be
   corrected in the same commit.
3. If no: drop the `expect=` from `formal-struct` in `tools/suite.py`, delete
   `bugs/FORMAL_struct_pack_over_eight_arguments.md`, and say in the commit
   that the arity ceiling is now untested rather than reporting it fixed.
4. Either way, `python3 tools/suite.py formal-struct` is the check, and it is
   red today.
