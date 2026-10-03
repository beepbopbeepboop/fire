# CODEGEN_bootstrap_stage2_dump_is_empty: the self-hosted binary exits 0 and writes no dump

## Status

Open. Measured on the 2026-10-03 full gate (commit `e59dae8c`, python3 3.14),
and re-confirmed on `master` as of `99cdb9b7`; nothing in the compiled path
changed in between, which is the measurement that makes this a standing class
rather than a fresh regression — see "Why this is not a new regression" below.

**The class, in one sentence:** `stage2/mojo --dump <file>` writes a correct
`.pyi`, an **empty** `.ci`, and **no** `.tok` or `.ast`, and exits 0 — so the
per-item fanout `bootstrap-stage2-dumps` passes while the files it produced are
not dumps. The failure is only visible downstream, in the two jobs that compare
the stage trees.

## What the gate reported

`bootstrap-verify` (`tools/bootstrap_verify.py`), verbatim from the run:

    verify: 47 identical, 87 stage1-vs-stage2 diff(s), 0 stage2-vs-stage3 diff(s),
            50 missing from a stage (184 files)

`bootstrap-validate` (`bootstrap-validate.mojo`), verbatim:

    FAILED: 256 mismatch(es) / 172 checked

and the per-file shape, verbatim, for one input:

    DIFF  test_struct.ci: stage1 vs stage2 first differ at byte 0
          test_struct.ci 31503 bytes vs test_struct.ci 0 bytes
    ok   test_struct.pyi
    MISSING test_struct.tok: present in stage1/
    MISSING test_struct.ast: present in stage1/

`bootstrap-validate.mojo` sums to 256 = 87 diffs x 2 (stage1-vs-stage2 and
stage1-vs-stage3, since stage2 and stage3 agree) + 82, so the two jobs are
counting the same thing in two vocabularies; they are not independent
witnesses.

**What that census says, read carefully:**

* `stage1` is right. `bootstrap-stage1-dumps` and
  `bootstrap-stage1-transitive` both PASS, and every `stage1/*.ci` has real
  content (31503 bytes for `test_struct.ci`, 1452022 for `myinterpreter.ci`).
  The reference is not the problem.
* **`stage2-vs-stage3` is 0 diffs.** The compiled binary is a fixed point of
  *itself*: run it twice and the second run reproduces the first, empty and all.
  So this is not nondeterminism and not a partial write — it is the binary
  computing something different from the reference, deterministically.
* 87 of 137 checked-and-present files (75%) are affected. This is the same
  shape as the long-standing per-file sweep in
  `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`, whose 2026-09-17
  status entry reads "Sweep: empty self-hosted outputs 38 -> 28" over a 779-file
  corpus. This doc is NOT a re-report of that sweep's *content*; it is the
  statement that the class is still present, is now the whole of what
  `bootstrap-verify` and `bootstrap-validate` report, and has a specific new
  signature (below) that the old census did not separate out.

## The new signature: `.pyi` right, `.ci` empty, `.tok`/`.ast` absent

This is the part worth writing down, because it is narrower than "the
self-hosted binary is wrong" and therefore cheaper to chase.

`--dump` is supposed to write four artifacts per input: `.ci` (the GIMPLE C),
`.tok` (the token stream), `.ast`, `.pyi` (the type stub). On the compiled
binary, for the inputs visible in the log:

| artifact | stage1 | stage2 |
|---|---|---|
| `.pyi` | correct | **correct** (reported `ok`) |
| `.ci` | 20-30 KB, thousands of lines | **0 bytes** |
| `.tok` | present | **absent** |
| `.ast` | present | **absent** |

A `.pyi` that is byte-identical to the reference next to a `.ci` of zero bytes
is the informative part. It says the self-hosted binary got far enough to
*parse and type* the file, and to run the type-stub emitter, and then produced
nothing for the three artifacts that come out of the code-generation and
tokenizer paths. That localises the defect to "the dump driver runs and its
early stages succeed; the C/token/AST writers do not", rather than "the binary
cannot parse Mojo" (which would have made `.pyi` wrong too) or "the binary
crashes" (which would be a non-zero exit, and `reject='mojo_unsupported_iter'`
exists precisely to catch the non-crashing no-op).

`.tok`/`.ast` being *absent* rather than empty is a second, separate fact and
may have a separate cause: a file that is never opened cannot be empty. It is
recorded here rather than folded into the `.ci` symptom because a fix for one
does not obviously fix the other.

## Why this is not a new regression

The gate that reported it ran on `e59dae8c`. Everything that has landed since,
to `99cdb9b7`, is `formal/` and test/tooling:

    $ git log --oneline e59dae8c..HEAD --name-only \
        | grep -E 'mojo/backend_gimple|mojo/middle|gimple_codegen\.py|module_loader\.py'
    (nothing)

`CLAUDE.md` names `mojo/backend_gimple/*` and `mojo/middle/*` as the files that
decide what the compiled binary computes, and none of them moved. So the
symptom is the standing class, not something the `bugs3` consolidation or the
`formal15` merges introduced. **This is stated as a measurement, not as a
bisect**: proving the negative properly needs a stage2 build on a pre-`bugs3`
tree, and a stage2 build is a self-host build, which this session was not
permitted to run (see "What was not run here").

## Why `bootstrap-stage2-dumps` is NOT the place this is caught

The fanout runs `[./mojo, '--dump', '../{file}']` per item and the runner's
per-item verdict is, in order: memcap, `reject=`, exit code. `reject` is a
**regex over the child's output** (`tools/suite.py`'s `run_job`), and a child
that writes nothing prints nothing. So the fanout's `reject='mojo_unsupported_iter'`
cannot see an empty file, and `bootstrap-stage2-dumps` reported **PASS** in the
same run in which 87 of its products were empty.

Two consequences, and both are already acted on:

1. **`bootstrap-stage2-dumps` had an `expect=` marker that is now stale**, and
   the runner correctly reported a marker whose test passes as a FAILURE. The
   marker is dropped. That is not a claim that the capability works — it is a
   claim that the *fanout* does not measure it, which is why the two jobs that
   do are the ones carrying the marker now.
2. **The marker was not the load-bearing part of the truth.** The old text
   (`SELFHOST_STAGE2_STALL` in `tools/suite.py`) said the sub-jobs "return
   `mojo_unsupported_iter` no-ops **or a wrong dump**". Measured 2026-10-03, the
   `mojo_unsupported_iter` half is GONE — that is why the fanout passes and the
   marker went stale — and the "wrong dump" half is exactly what
   `bootstrap-verify` reports. So the class did not go away; its *detector* in
   that job went away with it.

## The fix, when someone takes it

Nothing below was run here; it is the next step, written so it can be started
without re-deriving anything.

1. **Reproduce with one input, not three stages.** `stage2/mojo` is a single
   binary and `BOOTSTRAP_INPUTS` are single modules, so one command in `stage2/`
   is the whole reproduction:

       cd stage2 && ./mojo --dump ../test_struct.mojo ; ls -l test_struct.*

   No closure dump, no `stage3`, no `verify`. If `test_struct.ci` is 0 bytes
   there, the class is confirmed with the fan-out and the byte comparison out of
   the picture, and every question below is answerable in seconds.
2. **Ask which writer runs.** `--dump` should have one place that opens
   `<base>.ci`, one that opens `<base>.tok`, one that opens `<base>.ast`, and
   one that writes the `.pyi`. A single "did the dump succeed" boolean that
   everything downstream trusts is the thing to find: a path that opens the
   file, writes nothing, and reports success is the whole bug.
3. **The cheapest instrumentation that would have caught this in the fanout:**
   after the dump, `os.path.getsize` each artifact and print the sizes. That is
   one line per artifact, it needs no compiler change, and it turns
   `bootstrap-stage2-dumps` from "cannot see the defect" into "sees it on the
   first item". Until that exists, `expect=` on `bootstrap-verify` is what keeps
   this visible in the tally.
4. **Do not mark `bootstrap-verify`/`bootstrap-validate` `disabled=`.** They
   cost 0.6 s and 0.0 GB — they are three `os.listdir`s and a byte compare, and
   all of their cost is in `bootstrap-stage3-transitive`. Per `CLAUDE.md`'s
   rule (a known failure that is CHEAP runs, with `expect=`), `expect=` is the
   correct marker and `disabled=` would be paying the machine to be told what
   the doc already says.

## What was not run here

No stage tree was built. `stage1`/`stage2`/`stage3` are all absent from a fresh
worktree, and producing them is `fire.py build fire.py` plus a `gcc -O0` over
the 40 MB closure — a self-host build, which this worker was explicitly not
permitted to run. So: the census above is quoted from the gate log rather than
re-measured, and step 1 of "The fix" is where the re-measurement starts.

`bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md` is the doc that owns
the per-file CONTENT of the divergence (which files differ and why) and is not
edited by this one. It is cited here for the 2026-09-17 "empty self-hosted
outputs" census and nothing else.
