# FORMAL_sweep_tool_json_decode_error: three files get no verdict because the build driver is handed something that is not JSON, and the sweep files it as `tool`

**Status: found, not fixed.** Filed from the 2026-09-30 sweep re-measurement
(`bugs/FORMAL_sweep_work_map_2026-09-30.md` §5.1). Not claimed by any live
task at the time of filing.

**Re-measured the same day, later, on a tree 57 commits further on (`f378280d`):
1 file, not 3, and not one of the three.** The sweep now reports

```
TOOL: test_imports.py  (the build driver raised: json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0))
  tool                            1   no verdict reached: timeout, unreadable file, or an internal exception in the sweep or build driver
cas: 2 hit / 635 miss / 0 not cached (637 files)
```

where before it reported `std/gpu/compute/arch/mma_apple.mojo`,
`mojo/middle/stmts_shared.py` and `test_arm64_emission.py`. **The set moves with
the machine rather than with the tree**, which is the one thing none of the three
source files can explain: hypothesis 2 below — the child was killed or its output
truncated, and an empty stdout is exactly what `char 0` is — is now the leading
one rather than the second. Both runs were on a box with 18 sweep workers and a
16 GB ceiling, and this one ran concurrently with three other workers' sweeps.

So the class label is right (nothing was learned about the source) and the
diagnosis in the heading — "three files" — was a fact about one run.

## What is wrong

Three of the 628 files in the default arm64 sweep get **no verdict at all**,
every one of them with the same message:

```
TOOL: ../modular/mojo/stdlib/std/gpu/compute/arch/mma_apple.mojo  (the build driver raised: json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0))
TOOL: mojo/middle/stmts_shared.py                                   (the build driver raised: json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0))
TOOL: test_arm64_emission.py                                        (the build driver raised: json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0))
```

and the sweep's own summary accounts for them honestly:

```
  tool                            3   no verdict reached: timeout, unreadable file, or an internal exception in the sweep or build driver
  note: 3 file(s) got no verdict at all (timeout/unreadable/tool error) and are in NO rate; a too-small -t is the usual cause — this run used -t 30
```

`-t 30` is not the cause; the message is a decode failure, not a timeout, and
it arrives in well under the limit.

**Why this is filed rather than left as a note.** The classification is
*defensible* — `tool` is the class for "no verdict about the source was
reached at all", it is in no rate, and a run that counts 628 files and sums its
classes to 628 is telling the truth about what it knows. The problem is what it
costs: `json.decoder.JSONDecodeError` with `char 0` is not a "no verdict", it
is a **crash in the sweep's own or the build driver's plumbing** — a subprocess
whose stdout was empty, or whose stdout was not what the reader expected, read
as JSON. `tools/formal_sweep.py` has a class for exactly that shape
(`CAUSE_DRIVER_CRASH`, decided by the deepest traceback frame, and classified
as `backend-crash`), and this is landing in `tool` instead. So the class a reader
sees says "the sweep could not answer", when what happened is closer to "the
sweep asked a question and the answer was not an answer".

That distinction has teeth: `backend-crash` is a finding about the compiler's
plumbing and is printed and counted; `tool` is a finding about the run and is in
no rate. A reader triaging this tree would reasonably conclude the three files
are uninteresting, and one of them (`mojo/middle/stmts_shared.py`) is in the
compiler's own middle tier.

## The smallest reproducer

```
$ python3 tools/formal_sweep.py --no-stdlib -j 4 -t 60 mojo/middle/stmts_shared.py
…
TOOL: mojo/middle/stmts_shared.py  (the build driver raised:
      json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0))
```

## What to look at, in order

1. **`formal_sweep.py`'s `run_one` / `build_formal` invocation.** The build is
   a `subprocess` whose output is read with `json.loads` (or equivalent) and
   whose failure path is a bare `except Exception` that stamps
   `CAUSE_TOOL_ERROR`. Whatever the driver wrote — nothing, a traceback, a
   `memcap:` line, a `memslot:` waiting line — arrives at `json.loads` and
   becomes a decode error, which is a message about the PARSER rather than about
   what failed. Catching `ValueError` from the decode separately and reporting
   the child's exit status and first line of stderr would turn all three of
   these into the diagnostic they are.
2. **Whether the child was killed.** `Expecting value: line 1 column 1` is what
   an empty stdout looks like, and the three files are large (`mma_apple.mojo`,
   `test_arm64_emission.py`) or mid-stack (`stmts_shared.py`). A build that
   exceeded the sweep's own memory wrapper, or that `memcap` killed, would leave
   exactly this. **`build/suite.log` from a `make gate` run is the place to
   read it**: the runner prints the complete output of anything that failed, and
   a killed job is listed under `FAILED: … [TIMEOUT]` or as a `RESOURCE`
   verdict, which is a different thing from this.
3. **Only then** the possibility that it is a real defect in one of the three
   files — which the current classification makes invisible, because a crash
   and a decode failure share a class.

## What is measured, and what is not

* The three files, the message and the `-t 30` note: the 2026-09-30 arm64 sweep
  on current master (`24f96604`), full log at `.tmp/sweep_20260930.log` in the
  worktree that produced it.
* **NOT measured: why the child produced non-JSON.** No attempt was made to
  reproduce it outside the sweep, and the three hypotheses above are
  hypotheses. The first one to check is the cheapest and the one that would
  change the classification, so it is first.
