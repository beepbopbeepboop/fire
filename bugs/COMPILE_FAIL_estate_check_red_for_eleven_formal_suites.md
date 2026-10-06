# COMPILE_FAIL_estate_check_red_for_eleven_formal_suites: `test_suite.py`'s estate check was red for eleven files, and is twenty now

Not a compiler bug and not a codegen gap: a **registration** gap, and the
mechanism for closing it is already in the file. Recorded because
`test_suite.py` is in the everyday regression set and it is red for a reason
that has nothing to do with whatever you just changed, which is the most
expensive kind of red to read.

## One more arrival, measured the same way (2026-10-04, `work/merge-formal27b`)

`test_formal_per_struct_asks.py`, the check that pins "a per-struct table is
asked once per STRUCT, not once per FUNCTION" — the property behind the two
per-function askers `bugs/FORMAL_build_cost_2026-10-03.md` §6 named and
2026-10-04 closed. It arrived with `26cfcb21` ("PERF: the two per-function
askers of a per-struct table, and a check that pins the family"), which master
merged as part of `work/bugs5-1` (`08317416`), and neither `tools/suite.py` nor
`UNREGISTERED` names it:

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_suite.py
    Results: 326 passed, 1 failed
      - the estate: … not run by any registered spec and not in UNREGISTERED:
        test_formal_per_struct_asks.py

**What registering it costs (measured, because the answer decides it).**

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

So it is a registration and not an `UNREGISTERED` row: the excuse reason this
tree uses for the formal per-construct suites ("they build and RUN images on
both architectures against CPython, so a gate row costs minutes per file") is a
measurement of OTHER files, and this one is 1.1 s. What it pins is ask COUNTS
rather than a wall clock: a per-function asker back makes them grow with the
function count, and a deleted table makes them grow too.

**The exact next step.** One registration, in `tools/suite.py`, beside
`formal-field-walk` (which is the subject-mate: the statement walk the store
census reads through):

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

It is green and CHEAP, so it is a registration and not an
`UNREGISTERED` row — the excuse reason this tree uses for the formal
per-construct suites is a measurement of OTHER files:

## Status, after the merge

**One more arrived on 2026-10-03 and is NOT declared**, so the check is red
again on `master` today: `python3 test_suite.py` is `282 passed, 1 failed` with

    - the estate: every test file is run by something, or says why not:
      not run by any registered spec and not in UNREGISTERED: test_formal_tempfile.py

`test_formal_tempfile.py` landed with the `tempfile` host module
(`5b993959 formal: tempfile — the 111-file host-import row, ranked and then
modelled`) and added no `UNREGISTERED` entry. Measured directly rather than
assumed, since that is what has distinguished an unaccounted-for file from a red
suite in every paragraph above:

    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_tempfile.py
    # 7/7 groups passed (arm64, x86_64) — constants, gettempdir, candidates,
    # mkdtemp, name, exclusive, absent

**So it is green and undeclared, and the fix is one dict entry** —
`'test_formal_tempfile.py': _FORMAL_SUITE_REASON`. Not done here:
`tools/suite.py` and `test_suite.py` are `construct:estate-registration`'s write
set and this is a merge branch. The twenty-five arrivals this document has now
recorded (eleven, five, one) is the argument for the thing its own text says
twice: a hand-kept excuse list is the wrong instrument, because the inventory is
the set of `test_*.py` on disk and every new suite is a new obligation for
whoever adds it.

**The twenty are now declared; the gap is closed by an excuse, not by a
registration.** `test_suite.py`'s `UNREGISTERED` gained twenty entries, one per
file, all sharing `_FORMAL_SUITE_REASON` — so `python3 test_suite.py` is
`299 passed, 0 failed` where it was `200 passed, 1 failed`.

**Five more arrived on 2026-10-02 and are now declared too**, which is the
obligation this document describes landing again:
`test_formal_admitted.py`, `test_formal_fcntl.py`, `test_formal_math.py`,
`test_formal_shutil.py` and `test_formal_stat.py` — five host-module suites, each
from a different landing, none of which added its entry. Measured, each run
directly rather than assumed: `admitted` PASS=11 FAIL=0 SKIP=0, `fcntl` 5/5
groups, `math` 8/8 groups, `shutil` 9/9 groups, `stat` 4/4 groups — every one
green, so what the estate check was reporting was unaccounted-for files and not a
red suite. `python3 test_suite.py` was `298 passed, 1 failed` on the tree with
those five missing and is `299 passed, 0 failed` with them listed.

The count grew from eleven to fifteen while the doc sat, and from fifteen to
twenty after it, because per-construct and host-module suites land from other
branches (`test_formal_cross_module.py`,
`test_formal_eval_eq_mojo_bridge.py`, `test_formal_platform.py`,
`test_formal_specialized_method_call.py`, `test_formal_trait_module.py`,
`test_formal_type_application.py`, `test_formal_recursion_contract.py` among
them). That is the shape of the problem and the reason a hand-kept excuse list
is the wrong instrument: the inventory is the set of `test_*.py` on disk, so
every new suite is a new obligation and the list has to be edited by whoever
adds the file.

**What is still open is the registration itself**, and it is deliberately not
done here. Each of these is a `cmd` step that builds and runs N programs on two
architectures; a `formal` bucket entry for the group is a `cmd` with a memclass
and a timeout, and the honest version of that is one `Fanout` per suite over its
programs, which is what makes it a real change to `tools/suite.py` rather than a
line in a dict. That is `construct:estate-registration`'s row and it needs the
integration gate to measure; an excuse that says WHY is what the check accepts,
and that is now what it has.

## What it says

```
$ python3 test_suite.py
Results: 200 passed, 1 failed
  - the estate: every test file is run by something, or says why not:
    not run by any registered spec and not in UNREGISTERED:
    test_formal_argparse.py, test_formal_frame_len.py,
    test_formal_hashlib.py, test_formal_module_attr.py,
    test_formal_os.py, test_formal_os_backing.py, test_formal_sys.py,
    test_formal_time.py, test_formal_toplevel.py,
    test_llm/test_llm.py, test_struct_formal.py
```

Measured on `53f89ae7` (master) as well as on a tree carrying only this change,
so it is not caused by anything recent.

## Why it is a real gap rather than noise

`UNREGISTERED` in `test_suite.py:2029` is the file's own answer to "this test is
deliberately not in the gate": a dict from a `test_*.py` to **a sentence saying
why**. The estate check accepts either half — a registered spec or a sentence —
and these eleven have neither. Eleven suites that build and execute real
Mach-O images (`test_formal_os.py`, `test_struct_formal.py`,
`test_formal_frame_len.py`, …) are therefore invisible to every gate, to the
tally, and to the coverage number, and nothing in the tree says that is a
decision.

That is the failure mode `formal/build.py`'s check ORDER records from
the other direction: `coro` sat in the gate naming `mojo_*` runtime files after
they were renamed to `fire_*`, all twenty of its cases had been failing to
compile, and the suite had been reporting 0/20 the whole time. Here nothing fails
at all, which is quieter and the same class.

## The next step

One dict entry per file, each with a sentence. There is no analysis to do and no
risk: `UNREGISTERED` entries are checked for being non-empty strings
(`test_suite.py:2144`), and an entry changes no test's behaviour. A reasonable
sentence for most of them is the one used for
`test_formal_returned_frame.py` in `FORMAL_returned_frame_caller_owned_block.md`:
they build and execute images on both architectures and compare against CPython,
so a gate that ran them all would be minutes per job — which is a reason to run
them by hand and say so, not a reason to leave them undeclared.

**Owner: `construct:estate-registration`**, which holds `tools/suite.py`. Not
filed as a duplicate of that work; this is the measurement the entry needs.
