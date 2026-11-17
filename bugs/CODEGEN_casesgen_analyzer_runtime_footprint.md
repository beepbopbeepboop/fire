# CODEGEN: the compiled `Tools/cases_generator/analyzer.py` peaks at ~8.6 GB of RSS on `Python/bytecodes.c`

Status (2026-11-15, measured while landing the cases-generator analyzer fixes):
the output is CORRECT (byte-identical to CPython, 2892 lines, exit 0) but the
compiled program's own memory footprint is enormous and sits at the very edge
of the test driver's cap.

## What I ran

Built the analyzer from a fresh copy of the CPython source (the
`test_analyzer_build.py` shape), then ran the produced binary under
`/usr/bin/time -l` and sampled `ps` while it ran:

```
cp -R /Users/mrs/net/Python-3.14.6/Tools/cases_generator .tmp/x2/cases_generator
python3 fire.py build -o .tmp/x2/bin .tmp/x2/cases_generator/analyzer.py
/usr/bin/time -l .tmp/x2/bin /Users/mrs/net/Python-3.14.6/Python/bytecodes.c
```

## What I saw

```
1.40 real  0.76 user  0.61 sys
8642101248  maximum resident set size
604029      page reclaims
     2      page faults
     0      swaps
```

i.e. **8.64 GB maximum RSS for 1.40 s**. A `ps` sample during the run shows
6.58 GB at 0.4 s and 8.41 GB at 0.8 s. Scaling check: the same binary on an
empty input is 10 MB; on `bytecodes.c` it is 8.64 GB. VSZ is ~489 GB (the
4 GB `__PAGEZERO` plus mapped libraries; the binary's own segments are
~550 KB — `size -m` confirms no large `__DATA`/`__BSS`).

The output is right: `cmp` against `python3 analyzer.py bytecodes.c` is
identical (2892 lines). So this is a runtime allocation/shape problem, not a
wrong-answer problem.

## Why it matters

- `test_analyzer_build.py`'s docstring still says "~20 s, < 1 GB"; the run is
  now 1.4 s and ~8.6 GB. Its driver wraps the build in `memslot --gb 8` and the
  suite registers `reg-analyzer-build` as `mem='tiny'` (4 GB), so the compiled
  binary is **at or over both ceilings** — the test is flaky: run directly it
  can pass at 0.1-0.2 GB (a cached program binary) and fail with a RESOURCE
  breach when the binary is fresh.
- `reg-analyzer-build` is in the `regressions` bucket only (not in `check` or
  `gate`), so today's gate does not pay this; a sweep of that bucket will.

## Not caused by the output fix

The land that made the output identical (the `mojo_int_of_word` int() read,
the repr wrapper, the shadowed-builtin gate, the decorated-method gate) does
not allocate per call. The historical symptom was the *opposite* (a spin at
170K generator/s, `int(anno[10:-1])` handing a string pointer to
`range(...)`); that loop now terminates. This is a second, independent
footprint bug exposed by the analyzer finally reaching the end.

## Exact next step (measure before changing)

1. Build the analyzer with `-DMOJO_ALLOC_CENSUS` (see
   `runtime/fire_alloc_census.h` and `test_runtime_alloc_census.py`) and run
   it on `bytecodes.c`; read the atexit report for the top live-bytes sites.
2. In parallel, inspect the two obvious quadratic candidates in
   `runtime/fire_runtime.c`:
   - `_list_word_push` (around line 2072): it allocates a new kinds buffer on
     growth and never frees the old one, and it re-allocates + copies the
     whole kinds string unless `_kinds_row()->owned == 2` survives
     `mojo_list_set_kinds`. If `owned` is reset (or the row is not the same
     row) on each append, appending `n` tagged words is O(n^2) bytes — for
     the ~100K-token analyzer input that is the right order of magnitude for
     gigabytes.
   - `mojo_list_set_kinds` itself: confirm it stores the pointer and does not
     copy, and what it does to `owned`.
3. Pin the result with a peak-footprint assertion in
   `test_analyzer_build.py` (or a smaller run of the same program on a
   reduced input), and compare against CPython's own peak on the same input
   (tens of MB) rather than a hand-picked number.
