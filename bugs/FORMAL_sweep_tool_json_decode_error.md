# FORMAL_sweep_tool_json_decode_error: files get no verdict because the build driver read a manifest another process had truncated to zero bytes

**Status: SUPERSEDED — the mechanism is now MEASURED. See
`bugs/FORMAL_dylib_manifest_written_in_place.md`, which replaces this document
and should be read instead.** This file is kept because the sweep still files
these rows in `tool` and a reader who lands here needs to be sent on, and
because the re-measurement history below is the evidence that the cause was
never in the source files.

The short version: `formal/build.py` and `formal/imports.py` rewrite
`<dylib>.manifest.json` **in place**, and `open(path, "w")` truncates the file
to 0 bytes at the open. A reader in the 0.21 ms window before `json.dump`
writes its first byte gets an empty file, and `json.JSONDecodeError` is not an
`OSError`, so none of the `except OSError` around those reads catches it.
Measured on a real 11,668-byte manifest: **357 of 882 concurrent reads (40 %)
saw the empty file.** It is a race between two workers in ONE sweep that both
build the same stdlib dylib — not a killed child, and not a property of any of
the source files. The dylib *write* is `flock`-serialised; the reader takes no
lock, which is the entire bug.

## The original text, kept for the re-measurement history

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

**Do not start here — start at `bugs/FORMAL_dylib_manifest_written_in_place.md`,
which has the measured mechanism and the fix.** The three hypotheses this section
used to list are all now known to be wrong, and it is worth saying which is which
so nobody re-derives them:

1. ~~"`run_one` / `build_formal` reads the build's output with `json.loads`"~~ —
   no. `run_one` reads `proc.stdout`/`proc.stderr` as TEXT and never decodes
   JSON; the decode is `json.load` of a **manifest file**, inside
   `formal/build.py` and `formal/imports.py`, in the build driver.
2. ~~"The child was killed"~~ — no. Measured with no timeout,
   `std/python/bindings.mojo` runs 850 s at a flat 0.06 GB (a real, separate
   hang: `bugs/FORMAL_bindings_mojo_build_never_terminates.md`), but the files
   that produce this row do not wedge, and the empty file is accounted for
   without any kill.
3. ~~"A real defect in one of the source files"~~ — no, and the moving set of
   files is the proof: `mma_apple.mojo` / `stmts_shared.py` /
   `test_arm64_emission.py` on 2026-09-30, `test_imports.py` on a tree 57
   commits later, and 1 then 5 files in three `-j6` arm64 sweeps on
   2026-10-01. What those runs share is **contention**, not source: the counts
   track `-j`, and the one `-j18` run that showed none was the one where the CAS
   was warm and every worker finished in milliseconds.

## What is measured, and what is not

* The three files, the message and the `-t 30` note: the 2026-09-30 arm64 sweep
  on current master (`24f96604`), full log at `.tmp/sweep_20260930.log` in the
  worktree that produced it.
* **The mechanism, measured 2026-10-01** (`bugs/FORMAL_dylib_manifest_written_in_place.md`):
  300 in-place rewrites of a real 11,668-byte manifest against a concurrent
  reader produced 357 empty reads out of 882, with a 0.21 ms window per
  rewrite. Not a hypothesis any more.
* **NOT measured: which of the four manifest writers truncated the file** in any
  given occurrence. All four do the same thing and the fix covers all four, so
  this does not block anything — but a reader wanting to confirm the race
  end-to-end should sample the manifest's size while a sweep runs rather than
  guess from the file.
* **NOT fixed.** The fix is a temp-file + `os.replace` write through one shared
  helper, named in the successor doc. It is not in
  `formal/build.py`/`formal/imports.py` because this session's claim was
  `tools/formal_sweep.py`.
