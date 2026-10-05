# Two host-module reds that predate this merge: the sweep-truth dead-row list and the libc `retkind` census

**Status.** Open, and NOT this merge's. Both were measured red on `master`
(75114b34) by running master's own copy of each test file against this tree, so
neither is caused by `work/merge-formal25`. This merge *reduced* both.

## What I ran

    export PATH=/opt/homebrew/bin:$PATH
    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py
    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_libc_symbol.py

    # and, to establish that neither is this merge's, master's own copy of each
    # file against this tree's sources:
    git show master:test_formal_sweep_truth.py > _probe.py && python3 _probe.py; rm _probe.py
    git show master:test_formal_libc_symbol.py  > _probe.py && python3 _probe.py; rm _probe.py

## What I saw

**`test_formal_sweep_truth.py` — `test_the_premise_each_row_is_unbuildable`,
subtest `module='traceback'`:**

    AssertionError: 'formal/hostmods/traceback.mojo' is not None : `traceback`
    has a model at 'formal/hostmods/traceback.mojo', so importing it builds and
    this section does not apply to it any more

122 tests, 1 failed, 10 skipped. `traceback` got a model in `c1bc4613`
("formal: hostmods for `traceback` and `signal`, differential against CPython"),
and `_DEAD_ROW_MODULES` still lists it. The test is right to shout: its whole
subject is "these rows are dead imports", and a row that now has a model is not.

Master: **118 tests, 2 failed** — this one plus
`test_nothing_generates_a_lean_file_into_a_hard_coded_dir`, which `work/bugs5-4`
fixed (its `tools/tu_grind.py` scratch-directory commit). So this merge took the
file 2 → 1.

**`test_formal_libc_symbol.py` — `retkind`:**

    all 70 bare callees in formal/hostmods are either in BARE_C_RETURN_KINDS or
    in HOSTMOD_NON_C_CALLEES; unclassified: getpid
    (formal/hostmods/os/_syscalls.mojo), getpwnam (formal/hostmods/os/_syscalls.mojo),
    kill (formal/hostmods/os/_syscalls.mojo), strsignal
    (formal/hostmods/os/_syscalls.mojo)

10/11 passed. Master: **9/10 passed, 6 unclassified** — the same six minus this
merge's own `ed69d504` ("libc census: glob's basename/dirname are os.path's
own"), which cleared `basename` and `dirname`. So this merge took the file 6 → 4,
and **every remaining one is in `formal/hostmods/os/_syscalls.mojo`**, which came
in through the host-module batches and which this merge does not touch
(`git diff master --stat -- formal/hostmods/` is empty).

## What I expected

Green on both, or at least a red whose cause is in the tree the merge touched.

## Why neither is this merge's, and why it is not mine to fix

Both are in `formal/hostmods/`, which arrived through the host-module worker
waves (`hostmods-platform`'s `module:platform+fnmatch+collections-rest` and
`formal16-7`'s `sweep14:std-*` claims). The two things each needs are per-name
readings of someone else's modules:

* `test_formal_sweep_truth.py`: drop `traceback` from `_DEAD_ROW_MODULES` (it has
  a model), and check whether `signal` — the other module `c1bc4613` added —
  was in that list too or in the companion "has a model" table.
* `test_formal_libc_symbol.py`: classify `getpid`, `getpwnam`, `kill` and
  `strsignal` — each is either a `BARE_C_RETURN_KINDS` member or a
  `HOSTMOD_NON_C_CALLEES` member. `getpid` and `getpwnam` return `int`/
  `char *`; `strsignal` and `kill` are the same shape as the `basename`/`dirname`
  pair `ed69d504` resolved, so the precedent for the classification is already in
  the diff that commit made.

Editing `formal/hostmods/` is outside this merge's claim.

## Exact next step

    grep -n "_DEAD_ROW_MODULES" -A 12 test_formal_sweep_truth.py
    # drop `traceback`, check `signal`

    grep -n "BARE_C_RETURN_KINDS\|HOSTMOD_NON_C_CALLEES" formal/model.py
    # add getpid / getpwnam / kill / strsignal per ed69d504's reasoning for
    # basename/dirname, then:
    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_libc_symbol.py
    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py

Neither file is registered in `tools/suite.py`, so nothing in a gate catches
either today, and `test_suite.py`'s `UNREGISTERED` table is where a name is
excused. The same shape was found and fixed for five OTHER host-module files
(`test_formal_admitted/fcntl/math/shutil/stat.py`: unregistered and unexcused,
which is `suite-self-test`'s UNREGISTERED row going red) — that doc was deleted
with the fix, which is the right outcome, so this row is the one that has to
carry the claim now.

## Reproducing the "not this merge's" half

Both probes are the same two commands with `master:` substituted for the working
tree file. Keep them: a red that a merge "fixed" by editing the test rather than
the cause is the failure this pair of measurements exists to rule out, and both
of these got STRICTLY BETTER under the merge rather than worse.