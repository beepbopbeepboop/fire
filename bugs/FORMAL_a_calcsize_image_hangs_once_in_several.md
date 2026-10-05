# FORMAL: a `calcsize` image hangs for 60 s about once in six suite runs, and is clean 10/10 standalone

**Status: not reproduced, and the instrumentation is now EXCLUDED BY MEASUREMENT
rather than by argument; the format question this document left open is closed
by exhaustion; a THIRD candidate for the neighbourhood was found and filed.**
The hang itself is unexplained and this document stays open for it.

Found 2026-10-01 while re-running `test_struct_formal.py` to settle
`“CODEGEN_test_struct_formal: the struct suite is FLAKY”`. **NOT MINE and NOT FIXED** —
`formal/hostmods/struct.mojo`, `formal/arm64_codegen.py` and the image are
another worker's area; the harness that observes it is mine and is fixed
separately. Filed because `formal-struct` is a registered `proofs` job, a hang is
indistinguishable from a slow machine in a green-bucket report, and the symptom is
a formal image that runs forever.

## The original report, unchanged

Six runs of `test_struct_formal.py` on one tree, nothing changed between them.
Five reported the two declared failures and nothing else. One reported:

    FAIL  test_every_corpus_format_is_implemented raised: TimeoutExpired(
          ['/Users/mrs/net/chatgpt/claude/work-156/.tmp/struct_formal_6glh_fsd/corpus_HHIQQQI.bin'], 60)
    FAIL  calcsize("<HHIQQQI") == 36: the image was killed by SIGKILL (wait status -9), with no stderr
    ...
    122/127 checks passed

So one image — `calcsize("<HHIQQQI")` — BUILT successfully and then never
finished. Not slow: `RUN_TIMEOUT` is 60 s and a correct answer takes
microseconds. And in the same run the sibling case (`calcsize_<fmt>`, the same
source under the other test) was **killed by SIGKILL** rather than timing out,
which is a second symptom of the same neighbourhood and is worth the next
person's attention: something outside the process sent SIGKILL, and the two
things that can are a `memcap` ceiling and the OS.

## What was measured on 2026-10-02 (`work/formal8-1`), in the order the "next
## step" section asked for it

**Step 1 — re-run under a 8 GB ceiling: the hang does not reproduce, and the
ceiling is now excluded.**

```
$ for i in 1 2 3; do python3 tools/memslot.py --gb 8 --label sf -- \
      python3 test_struct_formal.py; done
174/174 checks passed
174/174 checks passed
174/174 checks passed

$ for i in $(seq 10); do python3 tools/memcap.py --limit-gb 8 -- cs_arm64.bin; done
36        (x10, exit 0 every time)
```

The corpus has also grown since the filing (174 checks now, against the 154 and
the 148 this document quotes), so this is not the same tree the failure was seen
on. **It is not an idle machine either** — other workers' jobs were in flight
throughout — so this is NOT the "close it, step 1 was the instrumentation"
verdict the next step contemplated, and it is not claimed as one.

**The SIGKILL half is settled, and it was never the compiler.** The failing run
was under `tools/memcap.py --limit-gb 1`. Measured for the same case, on the same
instrumentation:

```
$ python3 tools/memcap.py --limit-gb 1 --label csbuild -- \
      python3 fire.py build --formal --no-prove -o cs2.bin cs2.py
memcap: csbuild -- ceiling 1.0 GB across the process tree
Built: cs2.bin  [arm64/macho]
memcap: done, peak 0.04 GB across up to 1 procs (ceiling 1.0 GB), child exit 0
```

**0.04 GB against a 1 GB ceiling — 25x of headroom.** A `memcap` breach cannot be
what sent SIGKILL to a process that never came within 96 % of its ceiling, so the
`-9` came from OUTSIDE this build: the OS, under the machine-wide pressure
`CLAUDE.md` records for 2026-09-29 (about thirty compiler processes at 30-43 GB
each). That also makes the 60 s stall the same outside pressure rather than a
second, separate fault: a machine that cannot schedule a 60 KB image promptly is
a machine that was doing something else, and "the image is hung" is what a starved
process looks like from a 60 s timeout. **That is a narrowing, not an
explanation** — nothing here says what the pressure was.

**Step 4 — the arity question, which this document called "worth revisiting
anyway", is closed by exhaustion: there is no format walk that can loop.**

```
$ grep -n "def _nvalues" -A 40 formal/hostmods/struct.mojo
    if fmt == "<I" or fmt == "<i":  return 1
    …
    if fmt == "<HHIQQQI":          return 7
    return 0
```

`calcsize` is `while k < n` where `n = _nvalues(fmt)`, and `_nvalues` and
`_width_at` are **chains of string comparisons**, not walks over the format's
characters. So there is no loop whose bound depends on the format's spelling: a
format the module does not implement returns `n == 0` and `calcsize` returns 0
without entering the loop at all, and an implemented one runs exactly as many
iterations as it has values. `<HHIQQQI` names seven values and is inside the
eight-argument limit on both ABIs, so it is answered, and it is answered
correctly:

```
$ .tmp/w/cs2.bin                # calcsize("<HHIQQQI"), "<HHHHHH", "<4sBBBBBBB5x"
36 12 16                        # CPython: 36 12 16 — arm64 and x86-64
```

`pack_into` is the other half of the question and it is already guarded rather
than silent: `if n == 0 or n > 3: return 0`, so a format needing more values than
the six-argument signature has is DECLINED instead of half-written. So the
docstring's "a format needing more is left unwritten rather than written wrong"
is true of the code, and no part of this construct can produce a wrong number.

## The third candidate, found while doing the above

While re-running the corpus I hit a **real, reproducible failure in the same
suite**, and it is filed separately because it is a different signal:
`calcsize("<IIQQQQQQ")` built and then dyld refused to load one of its module
dylibs — "missing code signature", `SIGABRT`, exit 134 — because
`compile_formal_dylib` leaves the shared CAS path holding an UNSIGNED Mach-O for
the whole of a `codesign -s -` subprocess while every already-linked image on the
machine loads that path with no lock at all. Reproduced deterministically, with a
verified fix and one failed attempt recorded, in
`FORMAL_dylib_is_unsigned_at_its_shared_path_while_codesign_runs`.

It is **not** this document's cause — `SIGABRT` is neither a timeout nor a
`SIGKILL`, and the image in this document's report ran for 60 s rather than
refusing to load — but it is the third distinct "the image built and then did not
do the thing" symptom in one neighbourhood, and it is the only one of the three
with a known cause and a known fix.

## What is left, and it is small

The hang. Everything cheap has been measured:

* not the program (10/10, correct, exit 0, both architectures);
* not `memcap` (0.04 GB against a 1 GB ceiling, 25x headroom);
* not a format walk (there is none — the loop is bounded by a table);
* not the module's wide-format decline (it answers 36, CPython's answer, and the
  adjacent `pack_into` declines rather than truncating);
* not reproducible under an 8 GB ceiling on a busy machine (3 suite runs,
  174/174 each).

If it recurs, the image must be KEPT — `build_and_run`'s timeout message now
names the path, but `tmpdir` is a `TemporaryDirectory` — and the interesting
question is which of the two it was: a process that never got scheduled (look at
the machine, not the image: `build/suite.log` records the measured peak and the
runner records concurrency) or a process spinning inside the image (`tools/
gdbtool.py` on the live process answers that in seconds). **This document's
remaining content is a two-way branch for whoever sees it next, and the branch is
worth taking only with the image in hand.**

## Why the harness had to be fixed for this to be reportable at all

Before this, `TimeoutExpired` propagated out of the `for fmt in CORPUS_FORMATS`
loop, so the run reported 122/127 with nothing saying 21 checks had been
skipped, and a `build_and_run` that discarded `run.returncode` reported a
process that exited 3 as a PASS. `“CODEGEN_test_struct_formal: the struct suite is FLAKY”`
has that in full; the upshot here is that the next occurrence of this will name
the signal, name the image, and cost the rest of the suite nothing.