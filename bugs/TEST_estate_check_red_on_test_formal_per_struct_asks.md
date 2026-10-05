# `suite-self-test`'s estate check is red on `test_formal_per_struct_asks.py`: a test file on master that nothing runs

## Status

OPEN, measured, NOT fixed here — it is `master`'s, not this merge's, and rule 7
of the worker contract says a worker does not register anything in
`tools/suite.py` unless its task says so. Filed with the measurement, because
the fix is one line and the check it unblocks is in `check`.

## What I ran, and what I saw

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_suite.py
...
Results: 326 passed, 1 failed
  - the estate: every test file is run by something, or says why not: not run
    by any registered spec and not in UNREGISTERED: test_formal_per_struct_asks.py
```

## What I expected

Green. `test_suite.py`'s estate check is the check that every test file in the
tree is either run by a registered spec or carries a reason it is not — the
difference between *registering* a test and *excusing* one.

## Why it is red, and that it is not this merge's

The file arrived with `26cfcb21` ("PERF: the two per-function askers of a
per-struct table, and a check that pins the family"), which `master` merged as
part of `work/bugs5-1` (`08317416`) — before this merge started, and none of
the four branches this merge took part in mentions it:

```console
$ git merge-base --is-ancestor 26cfcb21 master && echo on master
on master
$ for b in work/gatefix9 work/bugs5-2 work/bugs6-1 work/bugs6-2; do
      git merge-base --is-ancestor 26cfcb21 $b && echo "$b yes" || echo "$b no"; done
work/gatefix9 no
work/bugs5-2 no
work/bugs6-1 no
work/bugs6-2 no
```

Neither `tools/suite.py` nor `test_suite.py`'s `UNREGISTERED` names it on
`master` either, so the red is on `master` as well as here:

```console
$ git show master:test_suite.py | grep -c test_formal_per_struct_asks
0
$ git show master:tools/suite.py   | grep -c test_formal_per_struct_asks
0
```

## What registering it costs (measured, because the answer decides it)

```console
$ /usr/bin/time -l python3 test_formal_per_struct_asks.py
7 passed, 0 failed, 7 checks
  real 1.142 s
  maximum resident set size 45 891 584 B (0.05 GB)
```

GREEN, 1.1 s, 0.05 GB, no Lean and no image — the price shape of
`formal-read-before-store` (8.5 s) and `formal-read-before-store`'s neighbour
`formal-field-walk` (0.08 s), both of which are registered in `check`. So this
is not an `UNREGISTERED` row: the excuse reason this tree uses for the formal
per-construct suites ("they build and RUN images on both architectures against
CPython, so a gate row costs minutes per file") is a measurement of OTHER
files, and this one is 1.1 s.

What the file pins, for the record: `formal/model.py`'s per-struct predicates
must be asked once per STRUCT, not once per FUNCTION — the property behind the
two per-function askers `bugs/FORMAL_build_cost_2026-10-03.md` §6 named and
2026-10-04 closed. The assertions are ask COUNTS, not a wall clock.

## The exact next step

One registration, in `tools/suite.py`, beside `formal-field-walk` (which is the
subject-mate: the statement walk the store census reads through):

```python
# `formal/model.py`'s per-struct predicates asked once per STRUCT rather than
# once per FUNCTION — the property behind the two per-function askers
# `bugs/FORMAL_build_cost_2026-10-03.md` §6 named. Measured 2026-10-04:
# 1.1 s, 0.05 GB, 7 checks, no image and no Lean (`/usr/bin/time -l`), which is
# `formal-field-walk`'s cost shape (0.08 s) and the reason this is a
# registration rather than an `UNREGISTERED` row.
test('formal-per-struct-asks', [PY, 'test_formal_per_struct_asks.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_formal_per_struct_asks.py', 'formal/model.py',
            'formal/build.py'],
     desc='a per-struct table is asked once per struct, not once per function')
```

plus the name in `check`'s formal block (`BUCKETS['check']`) and in
`MEASURED_PEAK_GB` as `'formal-per-struct-asks': (0.05, 'measured')`, and
`'test_formal_per_struct_asks.py'` in the `extraglob` of whichever registration
whose subject is "every formal test file" (`formal-admitted` walks
`formal/hostmods/`, so it is not the one).

Then `python3 tools/suite.py -j1 --list | grep formal-per-struct-asks` shows it
in a bucket, and `python3 test_suite.py` is 327 passed, 0 failed.