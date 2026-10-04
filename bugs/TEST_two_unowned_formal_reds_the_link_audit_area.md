# TEST_two_unowned_formal_reds_the_link_audit_area

**Area:** `test_formal_sweep.py` (the dyld-probe fixture group),
`test_formal_libc_symbol.py` (the `retkind` census) · **filed 2026-10-04, NOT
fixed** · found while landing the naming half of
`the link audit's naming of an unlowered callee.md`

Two tests in the formal backend's own area are red on `master`, neither is in
`bugs/` and neither is claimed. They are filed together because the thing worth
knowing about them is the same: **each is red for a reason that is not its
subject**, which is why each has survived — a red that named its own cause would
have been picked up.

## 1. `test_formal_sweep.py::test_a_bind_name_that_itself_begins_with_an_underscore_resolves`

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep.py
    Ran 124 tests … FAILED (failures=1)
    FAIL: TestDyldProbe.test_a_bind_name_that_itself_begins_with_an_underscore_resolves
    AssertionError: False is not true : [x86_64] precondition: the bind 'exit'
    does not begin with an underscore, so lstrip('_') cannot change it and this
    fixture tests nothing (the shape to reach for is a relative import from a
    module whose own NAME begins with an underscore)

**The test asserts its own FIXTURE is right, before asserting the behaviour**,
and the fixture picks the first bind name it finds — which is `exit`, a libc
symbol. The property under test is the double-underscore normalisation
(`FORMAL_dylib_export_audit_adds_a_second_underscore.md`'s subject), which needs
a name that ALREADY begins with one. The assertion's own failure message says
so and names the shape to reach for.

**Next step:** pick the fixture symbol by predicate — a bind name from a library
this file builds that starts with `_` — rather than by position, and say in the
fixture why the position was not enough. This is a defect in a TEST, and per
CLAUDE.md a failing test is not to be deleted or relaxed; it is to be made to
test what it says it tests.

## 2. `test_formal_libc_symbol.py::retkind`

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_libc_symbol.py
    9/10 passed
    FAIL retkind  all 66 bare callees in formal/hostmods are either in
      BARE_C_RETURN_KINDS or in HOSTMOD_NON_C_CALLEES; unclassified: basename
      (formal/hostmods/glob.mojo), dirname (formal/hostmods/glob.mojo)

Two callees of `formal/hostmods/glob.mojo` are in neither table. They are the
POSIX `basename`/`dirname`, so the answer is almost certainly
`BARE_C_RETURN_KINDS` (a `char *`) — but "almost certainly" is not what this
census accepts, and `formal/hostmods/glob.mojo` is host-module source whose C
return types are a property of the C library it wraps.

**Next step:** read the two declarations in `formal/hostmods/glob.mojo`, add each
to the right table with a comment saying which C function it binds and what it
returns, and re-run the census. If either one's answer is genuinely not a C
return kind, it belongs in `HOSTMOD_NON_C_CALLEES` — and the test's own second
line ("every HOSTMOD_NON_C_CALLEES entry is a name the census found; stale:
str_alloc") shows the table is already carrying a stale entry, which is the same
class of drift one row over.

## 3. A third kind of hole, found in the same run: two test files nothing runs

`test_suite.py`'s own estate check, on `master`:

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_suite.py
    Results: 298 passed, 1 failed
      - the estate: every test file is run by something, or says why not: not
        run by any registered spec and not in UNREGISTERED:
        test_formal_field_walk.py, test_formal_glob.py

Two `test_formal_*.py` files are not in any bucket and not in `UNREGISTERED`, so
**nothing runs them and nothing says why not.** That is the shape
`bugs/TEST_registered_tests_in_no_bucket_never_run.md` was about for registered
tests; these are not even registered, so they are worse — they are files nobody
claimed and the estate check is the only thing that can see them.

**Next step:** register both in `tools/suite.py` with their measured `mem=`,
or add them to `UNREGISTERED` with the reason. Both were green when this was
measured (`test_formal_field_walk.py` OK, and `test_formal_glob.py` is a glob
census), so the first is a table row and the second is a judgement.

## Why they are filed together rather than fixed here

Both fixes are small, and the reason they are not made is worth recording
rather than the fixes themselves: this pass was inside
`the link audit's naming of an unlowered callee (landed in ee704916)`, whose scope is
a message's wording, and the honest reading of both failures is that they were
ALREADY red and have nothing to do with it. Both were measured to predate the
change by reversing it and re-running:

    $ git diff master -- formal/ tools/ > .tmp/wip.patch
    $ git apply -R .tmp/wip.patch && python3 test_formal_sweep.py    # same 1 failure
    $ python3 test_formal_libc_symbol.py                             # same 9/10
    $ git apply .tmp/wip.patch

That measurement is the only reason these two are a bug doc rather than a
regression, and it is the step a reader would otherwise have to invent.