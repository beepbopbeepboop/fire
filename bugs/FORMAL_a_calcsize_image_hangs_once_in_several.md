# FORMAL: a `calcsize` image hangs for 60 s about once in six suite runs, and is clean 10/10 standalone

Found 2026-10-01 while re-running `test_struct_formal.py` to settle
`bugs/CODEGEN_test_struct_formal_is_flaky.md`. **NOT MINE and NOT FIXED** —
`formal/hostmods/struct.mojo`, `formal/arm64_codegen.py` and the image are
another worker's area; the harness that observes it is mine and is fixed
separately. Filed because `formal-struct` is a registered `proofs` job, a hang
is indistinguishable from a slow machine in a green-bucket report, and the
symptom is a formal image that runs forever.

## What I ran, and what I saw

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

## What is NOT the cause, measured

* **Not the program, in isolation.** Built and run 10/10 from one build each,
  `.tmp/w/h1.bin`:

      $ for i in 1..10; do /usr/bin/time -p .tmp/w/h$i.bin; done
      36 real 0.60 user 0.00 sys 0.00
      36 real 0.00 user 0.00 sys 0.00      (x9)

  Correct answer, exit 0, first run 0.6 s (cold cache) and 0.00 s after. So the
  image is not deterministically looping; whatever happens is a property of the
  BUILD or of the machine, not of the emitted code.

* **Not `struct.mojo`'s wide-format decline.** `calcsize` is not `pack`, and
  `<HHIQQQI` names seven values with an EIGHT-argument `calcsize(fmt)` call —
  well inside the ABI limit, unlike the two cases
  `bugs/FORMAL_struct_pack_over_eight_arguments.md` is about. It is not that
  doc's bug and fixing that would not touch this.

* **Not a truncated artifact from the shared CAS.** `cas.publish`
  (cas.py:608) writes a private temp, `fsync`s and `os.replace`s it, and its
  docstring says why a racing identical write is harmless. There is no window in
  which a reader can see a partial file.

## Not excluded — do not skip these

* **My own instrumentation.** The run was under `tools/memcap.py --limit-gb 1`
  (the suite's measured peak is 0.1 GB, so 1 GB looked generous and the machine
  was full of other workers' jobs). A `memcap` breach sends SIGKILL to the tree,
  which would explain the `-9`; and whether it can also produce the 60 s
  apparent hang is not established. **Re-run under `--limit-gb 8` before
  concluding anything about the compiler.** The SIGKILL and the hang are both
  consistent with a ceiling that is too tight, and the SIGKILL's own answer is
  in `build/suite.log`, which records a measured peak per job.
* **Load.** `memslot` serialises the memory RESERVATION and nothing else, so
  N suites can be in flight at once. The hang happened on the one run of six
  that was competing hardest.

## The next step, in order

1. **Re-run `formal-struct` alone, with `--limit-gb 8`, on an idle machine,
   several times.** If the hang does not reproduce there, step 1 was the
   instrumentation and this doc closes with that finding. If it does, the
   ceiling and the load are both excluded and the compiler is implicated.
2. **Keep the hung image.** `build_and_run`'s timeout message now names the
   path (`the image was built and then did not finish within 60s — it is hung,
   not slow…`) — but `tmpdir` is a `TemporaryDirectory` and the image is deleted
   with it. Copy it out before the run ends, or run the case by hand:

       $ cat > /tmp/w/c.py <<'EOF'
       from struct import calcsize
       def main():
           print(calcsize("<HHIQQQI"))
       EOF
       $ python3 fire.py build --formal --no-prove -o /tmp/w/c.bin /tmp/w/c.py
       $ /tmp/w/c.bin &          # then: sample it, or attach tools/gdbtool.py

   (`/tmp` is only for this throwaway; in a worktree it is `.tmp/`.)
3. **If it reproduces: `tools/gdbtool.py` on the live process**, `HOW-TO-DEBUG.html`
   for the rest. The interesting question is which loop it is in — `calcsize`'s
   format walk in `formal/hostmods/struct.mojo`, or something in the emitted
   prologue — and that is answerable in seconds from a stack.
4. **Whichever way it goes, the arity question is worth revisiting anyway.**
   `<HHIQQQI` names seven values and `<HHHHHH` six, and the emitter refuses at
   the call site only past eight arguments, so these are inside the limit and
   the module's own decline should be what happens. A format walk that can loop
   on a format `struct.calcsize` accepts is a real bug whatever triggered the
   hang, and `bugs/FORMAL_struct_pack_over_eight_arguments.md` already has the
   emitter side of it.

## Why the harness had to be fixed for this to be reportable at all

Before this, `TimeoutExpired` propagated out of the `for fmt in CORPUS_FORMATS`
loop, so the run reported 122/127 with nothing saying 21 checks had been
skipped, and a `build_and_run` that discarded `run.returncode` reported a
process that exited 3 as a PASS. `bugs/CODEGEN_test_struct_formal_is_flaky.md`
has that in full; the upshot here is that the next occurrence of this will name
the signal, name the image, and cost the rest of the suite nothing.