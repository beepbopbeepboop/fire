# Makefile recipes run under memcap's fixed 20-minute default (no explicit time limit)

Found 2026-11-23 reviewing `261b6690a` ("memcap: a wall-clock limit that always applies").

memcap now kills any run that outlives `--time-limit-min` (default 20, and it cannot be disabled).
`tools/suite.py` passes each suite job's own timeout, so suite jobs are fine. But Makefile recipes
get their wrapper from `$(call memslot,<label>,<class>)`, which expands through
`tools/suite.py --prefix` (`print_wrapper_prefix`, tools/suite.py ~line 7061). That prefix passes
`--gb` and nothing else, so every recipe gets the 20-minute default:

    Makefile:415  $(call memslot,mojoc,module)       fire.py build fire.py   (whole-closure build)
    Makefile:451  $(call memslot,stage2/mojo,small)  gcc of the ~135 MB stage1/fire.ci
    Makefile:478  $(call memslot,fire.ci,tiny)       fire.py --dump-full
    Makefile:482  $(call memslot,build/system.o,tiny)

Today these take about 1-8 minutes (stage2 cc about 50 s; the closure dump 5-8 min). The commit's
own example names `--time-limit-min 90` for a `mojoc --dump-full`. A whole-closure `make mojoc` on a
loaded machine is the one that can go over 20 minutes, and then it is killed with exit 124 instead of
finishing. Nothing says why except the `memcap: TIMEOUT` line.

## What to do

1. Give `print_wrapper_prefix` a time limit: a per-class default table next to `MEMCLASS` in
   `tools/suite.py` (for example tiny 20, small 30, module 60, program 90, stage 120 minutes), passed
   as `--minutes` to memslot (which forwards it to memcap).
2. Use the existing `--prefix WRAPPER LABEL CLASS` interface. Do not hard-code minutes in the
   Makefile: the point of `$(call memslot,...)` is that the numbers live in `tools/suite.py`.
3. Add a case to `test_suite.py` that the printed prefix contains `--minutes` with the class's value.

## Checks

    python3 tools/suite.py --prefix memslot mojoc module     # shows --gb ... --minutes ...
    python3 test_suite.py                                     # 0 failed
    python3 test_memslot.py && python3 test_procrun.py

Delete this doc in the same commit.
