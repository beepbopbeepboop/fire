# Eight `test_*.py` files are on disk and run by nothing: `suite-self-test` is red

## Status

OPEN — pre-existing, and found (not caused) while assigning memclasses. Nothing
in this repo's gate runs `test_suite.py`, so this is a red that a gate cannot
see, which is the part worth fixing first.

## What is believed

`test_suite.py`'s estate check requires every `test_*.py` in the repo to be
either named by a registered `tools/suite.py` spec or listed in its
`UNREGISTERED` table with a reason. On the merged round-8 tree (2026-09-30,
`merge3-stragglers`), **ten** files satisfy neither:

    test_dataclasses_formal.py  test_formal_argparse.py
    test_formal_frame_len.py    test_formal_hashlib.py
    test_formal_os.py           test_formal_sys.py
    test_formal_time.py         test_formal_toplevel.py
    test_llm/test_llm.py        test_struct_formal.py

Two of those arrived with the round-8 merges and are new since the eight below
were counted, which is the regression happening live rather than historically:

  * `test_dataclasses_formal.py`, with `work/mod-dataclasses` (merge
    `cefec66d`). Its sibling `work/mod-re` DID register its own test
    (`formal-re`), so this is an omission in that branch rather than a
    deliberate decision.
  * `test_llm/test_llm.py` — which the earlier count of eight also missed, so
    the list here was already incomplete when written. It lives in a
    subdirectory, which is worth knowing if the walker is ever narrowed.

`work/ab-native-tempfiles` filed the same hole independently as
`UNTESTED_three_formal_test_files_run_by_nothing.md` (naming
`test_formal_os.py`, `test_formal_sys.py`, `test_struct_formal.py` — a strict
subset of the eight). That doc is folded in here and deleted: one hole, one
doc. Its value was the second confirmation, on a different day and from a
different task, which is why the "pre-existing" claim below is not resting on
one session's reading.

## What was run, and what it showed

    python3 test_suite.py
    FAIL  the estate: every test file is run by something, or says why not:
          not run by any registered spec and not in UNREGISTERED: ...
    Results: 199 passed, 1 failed

    # and, to establish that it is not the memclass work above:
    git show 86d862f:test_suite.py > test_headcheck.py && python3 test_headcheck.py
    FAIL  the estate: every test file is run by something, or says why not: ...

So this is red on the pristine tree, and the memclass change neither caused nor
fixed it. It is also not in any bucket: `suite-self-test` is in `smoke`, and
`gate` is `check + coroutine + stdlib + native + bootstrap` — `smoke` is not in
it. `make check-suite` runs it, so it is one command away, but the number a
developer reads after `make gate` says nothing about it.

Still red after the round-8 merges, with the count at ten:

    $ python3 tools/suite.py smoke -j2
    FAIL     suite-self-test  (33s)  exit 1
    suite: 2 passed, 1 failed, 0 skipped  (3 tests, 3 jobs, ... 61.7s wall)
    $ grep '^FAIL ' build/suite.log
    FAIL  the estate: every test file is run by something, or says why not: ...

The `grep` matters: `suite-self-test`'s ONLY failure is the estate check, so
`smoke` is otherwise green on this tree and the one red line is this hole.

That is the real defect: **the inventory of what runs is itself outside the
gate.** CLAUDE.md's argument for the registry is that "a test that only runs
in a bucket nobody runs daily is not guarding the property it was written
for" — which is the reason `silentnoop` is in `check`. The same argument puts
`preflight` and `suite-self-test` in `check` (both are sub-second, both are
load-bearing for everything else), and neither is there.

## Why it matters beyond tidiness

`bugs/UNTESTED.md` was written because 50 test files were named by no
registered spec, and the estate check was the fix. That fix does not hold
without two things it currently lacks: the check runs somewhere nobody skips,
and a newly added test file lands with a registration or a reason. Eight files
arrived without either, which is the same regression as the original 50, one
file at a time.

## The next step, exactly

1. Register the ten files. Nine are formal-backend tests and belong in the
   `formal-*` family; the spec shape to copy is `formal-re`
   (`tools/suite.py`, added by `work/mod-re`):

       test('formal-dataclasses', [PY, 'test_dataclasses_formal.py'],
            deps=['preflight'],
            extra=['test_dataclasses_formal.py',
                   'formal/dataclass_transform.py', 'formal/build.py',
                   'formal/imports.py'],
            desc='@dataclass as a compile-time transform, against CPython')

   `test_dataclasses_formal.py` is measured: 50 checks, 9.5 s, 0.1 GB peak
   under `tools/memcap.py`, so `mem='tiny'` is the honest class and the
   default (`small`) is merely safe. Every other formal test that builds
   images wants `deps=['preflight']` at minimum. `test_llm/test_llm.py` is not
   a formal test and goes wherever its subject belongs, or into `UNREGISTERED`
   with a reason.

   An entry in `UNREGISTERED` is also a declaration and is enough to make the
   check green — which is why the check is worth keeping and why a declaration
   has to be a reason, not a shrug. Registration is the better answer for all
   ten, because nine of them exist to keep a host module honest and the
   accounting test in `test_formal_link_accounting.py` already NAMES each of
   them as the thing that holds its module in place.
2. Put `preflight` and `suite-self-test` in the `check` bucket. `preflight`
   already runs in almost every `gate` — it is a `deps` of seven of `check`'s 21
   members and of `mojoc`/`ab-native`/`native-dumpfull` — but as a dependency
   rather than as a counted test, so it is invisible in the tally. (That is also
   why the estate check is not red more often than it is: an estate failure is
   a FAIL on `suite-self-test`, and `suite-self-test` is in no bucket at all.)
   `suite-self-test` itself is 37 s of synthetic specs with no toolchain here —
   a cheap way to make "the runner is broken" a gate failure rather than a
   thing someone notices a week later.
3. If neither is wanted in `check`, the honest alternative is a `make check-estate`
   target that the integrator runs, and a note in CLAUDE.md saying so. What is
   not honest is leaving a coverage check outside every gate, because that is
   how 50 files became 94.
