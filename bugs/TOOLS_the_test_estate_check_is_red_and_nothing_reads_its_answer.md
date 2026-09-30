# TOOLS_the_test_estate_check_is_red_and_nothing_reads_its_answer: `suite-self-test` fails on fourteen orphans, and the check is in no bucket the gate runs

**Area:** TOOLS / the test registry: `test_suite.py`'s estate check, the
`UNREGISTERED` table above it, and `tools/suite.py`'s `smoke` bucket.

**Found while:** landing `work/formal-cross-module` and running
`python3 test_suite.py` as the narrowest check that could see whether a new
`test_*.py` was accounted for. It is not, and the reason it is not is a shape
problem rather than a missing entry.

**Renamed 2026-09-30.** The slug used to end `…_since_eight_formal_suites_
landed`, which is a count in a filename, and the `integ` merge moved the count
from eight to fourteen — so a reader who found the doc by its old name would
have been told a number the tree no longer agrees with. The bug is not the
count; the bug is that the check's answer is read by nothing. That is the name.

**Status: OPEN, measured, red on `master` today.** Not caused by this branch —
this branch added the ninth file and is the one that made the list longer, not
the one that made the check red.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label suite-self-test -- python3 test_suite.py
...
Results: 170 passed, 1 failed
  - the estate: every test file is run by something, or says why not: not run
    by any registered spec and not in UNREGISTERED: test_formal_argparse.py,
    test_formal_frame_len.py, test_formal_hashlib.py, test_formal_json.py,
    test_formal_module_attr.py, test_formal_os.py, test_formal_os_backing.py,
    test_formal_pathlib.py, test_formal_small_hosts.py, test_formal_sys.py,
    test_formal_time.py, test_formal_toplevel.py, test_formal_x86_64_dylib.py,
    test_struct_formal.py
```

**Fourteen, and the `integ` merge added six of them** — `test_formal_json.py`,
`test_formal_module_attr.py`, `test_formal_os_backing.py`,
`test_formal_pathlib.py`, `test_formal_small_hosts.py` and
`test_formal_x86_64_dylib.py` — each landing with its hostmod and each with no
spec. `test_formal_cross_module.py` is this branch's own file and it carries a
`UNREGISTERED` entry (with the one-line spec that belongs to it written out in
the entry), so it is not on the list. Nothing else in the list is excused.

Two of the fourteen are RED as well as unregistered, which is worth separating
because they are different problems and a reader should not conflate them:
`test_formal_pathlib.py` is 2/7 on an unannotated parameter compared to a string
(`FORMAL_pathlib_suite_is_two_of_seven_on_an_unannotated_param_compared_to_a_
string`), and `test_formal_argparse.py` is 2/7 on a cross-dylib call whose
callee declares no return type. **Registering a red suite turns a red nobody
reports into a red everybody reports** — which is the right direction and is
step 1 below, but it means step 1 alone will make `proofs` red where it is
currently green-by-omission.

## Why it is red on `master`, measured rather than inferred

`bugs/UNTESTED.md` §4 mutation-tests this exact check — "every `test_*.py` is
registered, or declared with a reason", broken by "dropping one entry from the
50", detected by 2 checks. So the check is not vacuous and was not always red.
What moved is the input. Every one of the original eight was added to the repo
AFTER `UNTESTED.md` was written, so "50 of 81" was a true measurement when it was
taken and is not now:

| file | added | commit |
|---|---|---|
| `test_formal_os.py` | 2026-09-29 11:29 | `bba49bfa` |
| `test_struct_formal.py` | 2026-09-29 11:42 | `bb16b34a` |
| `test_formal_toplevel.py` | 2026-09-29 21:33 | `46ae5fa9` |
| the other five | 2026-09-29, after 02:15 | — |
| the six from `integ` | 2026-09-30 | `integ` |

`bugs/UNTESTED.md` landed at `82b9acc2`, 2026-09-29 02:15, and is an ancestor of
`master`. So each of these eight commits added a `test_*.py` that no spec names
and that no `UNREGISTERED` entry excuses, and each turned a green check red.
Eight times — and then the `integ` merge did it six more times in one commit,
which is the shape that matters: **a single integration commit can add six
orphans, so the per-file argument ("it was one file, one oversight") does not
scale and the check has to be read by something.**

## Why nobody noticed: the check is in no bucket the gate runs

```console
$ python3 -c "import sys; sys.path.insert(0,'tools'); import suite; \
    print([b for b,n in suite.BUCKETS.items() if 'suite-self-test' in n])"
['smoke']
$ ... # suite.BUCKETS['gate'] == ['check', 'coroutine', 'stdlib', 'native', 'bootstrap']
```

`gate` is `check + coroutine + stdlib + native + bootstrap`, and `smoke` is
none of them. So the one check whose subject is "is anything in this repo
actually being run" is itself run by nothing the gate runs. CLAUDE.md's "the
gate is otherwise clean: `check` 11/11" is not evidence about this file,
because `check` does not contain it — which is the same trap the gate section
warns about for `expect=`-marked tests, arrived at from the other direction.

## The exact next step

Two lines, in this order.

1. **Register the fourteen, or excuse them.** They are not throwaway files: each
   is a real suite over a hostmod this backend had to be taught, and
   `test_struct_formal.py` is what keeps `formal/hostmods/struct.mojo`
   byte-for-byte against CPython. The natural home is `proofs`, beside
   `formal-run` / `formal-dylib` / `formal-imports`, and each needs a memclass
   that admits the images it builds — `test_formal_os.py` builds a dozen.
   `test_struct_formal.py` has no suite at all and the cheapest correct answer
   for it is a `smoke`-bucket spec, because it needs no Lean and no image.
   **The two red ones first, and expect `proofs` to go red when they land:**
   `test_formal_pathlib.py` and `test_formal_argparse.py` fail on the two
   defects named above, and a registered red is a better state than an
   unregistered one, but it is a red the gate will start reporting and someone
   has to own each.
2. **Put `smoke` in a bucket the gate runs**, or move `suite-self-test` into
   `check`. `check` is the everyday subset and its whole claim is that a
   synthetic, millisecond suite belongs in it; the estate check is exactly
   that, and it is the only one of the three `smoke` members that can go red
   from ordinary work. `memslot` and `preflight` are import-level smoke and can
   stay where they are.

Step 2 is the one that matters. Step 1 fixes today's red; step 2 is what stops
the next integration commit from adding six more.

## Not this

- It is **not** the anti-rot guards failing. Both
  ("no excuse outlives its file" / "…its registration") pass; the
  `UNREGISTERED` table is honest about the files it names. The failure is the
  orphan walk finding fourteen real orphans.
- It is **not** "registration is broken". `test_suite.py` finds the fourteen
  correctly — that is the check working. The bug is that its answer is not
  read.
