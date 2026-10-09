# FORMAL: `no_public_api_reason`'s constants-only sentence lost the "backend RULE" clause its own test pins

**Area:** `formal/build.py::no_public_api_reason` (the constants-only branch) and
`test_formal_imports.py::test_a_constants_only_module_is_not_told_nothing_could_be_added`.
**Status: OPEN, diagnosed, not fixed. Pre-existing on `master`; found while
running `test_formal_imports.py` as a regression check after an unrelated change
to `imported_callee_refusal` (which does not touch this function).**

## What I ran

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
    ...
      FAIL  a constants-only module is not told nothing could be added
            the refusal does not say the missing thing is a backend RULE rather
            than work on the module, which is the part a reader acts on: formal
            dylib has no public functions: constants_only.mojo exports nothing
            under doc/ABI.md's rules because it declares no function and no type
            at all — only module-level constants, ... Neither exists here, so
            this is refused at the build rather than linked as a library with
            nothing in it, and nothing here is waiting on this file.
    formal imports: PASS=88 EXPECTED=0 SKIP=0 FAIL=1

## What was seen

The test's own last assertion is

    check("BACKEND" in reason, ...)

and the constants-only sentence `no_public_api_reason` returns today contains no
`BACKEND` anywhere. It names the two things that would remove the refusal (a
value model for a container constant, and a rule that a module nothing binds
needs no library) but it no longer says the missing thing is a decision about
the **backend** rather than work on the module — which
`bugs/FORMAL_std_os_io_round2_scope_is_one_refusal_shape.md` §0.4 says the
sentence was changed to say.

**The two sides are in git and the sentence is the one that moved.** Both the
test and the clause were added by `c1f99d80` ("formal: a constants-only module is
not told \"nothing this backend could add\""), where `formal/build.py` contained
the literal `work on the module but a decision about the BACKEND: those`.
`git show master:formal/build.py | grep -c BACKEND` is **0** and
`git show master:test_formal_imports.py | grep -c '"BACKEND" in reason'` is
**1**, so this is red on `master` and not a property of any one worktree: a later
edit to the sentence dropped the clause and left the guard that checks it.

## What is expected

The constants-only branch should say the missing thing is a rule about the
backend, as `FORMAL_std_os_io_round2_scope_is_one_refusal_shape.md` §0.4 and the
test both state. The exact next step is to restore that clause in
`no_public_api_reason`'s constants-only return (the other two branches are
different facts and must not gain it — the test's private sibling asserts
`"BACKEND" not in other`), then re-run
`python3 test_formal_imports.py` and require the one failure to clear. This is
the owner's (`bug:FORMAL_std_os_io_round2_scope_is_one_refusal_shape`, worker
`formal217-docs`) area, so it is filed rather than fixed from here.

## Why it is not fixed here

The refusal, its test and the doc that owns it are all in another worker's
claim. The finding is one sentence and one clause, and it is red on every gate
until it is restored, so it cannot rot unnoticed.
