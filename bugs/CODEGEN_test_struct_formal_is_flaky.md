# CODEGEN_test_struct_formal: the suite's TOTAL moved with its own verdicts, and one case reported a dead process as correct

Found 2026-09-30 and rewritten 2026-10-01, because the central claim in the
original — that this suite is FLAKY — is **refuted by measurement**, and the
thing underneath it turned out to be three separate defects in the harness, all
now fixed and all now checked. **The residual, a genuine intermittent hang, is
filed separately** as `bugs/FORMAL_a_calcsize_image_hangs_once_in_several.md`
and is the formal tier's, not this file's.

## What the original claimed, and what the tree actually does

Four runs of an unchanged tree, reporting 148, 147, 145 and 144 checks, with
`calcsize` cases printing nothing. The reading was "the total itself moves, so
some checks did not run — this is a harness defect as much as a flake".

Four runs of this tree, 2026-10-01, nothing changed between them:

    146/148   run 1 — the two declared failures, nothing else
    122/127   run 2 — plus a TimeoutExpired on calcsize("<HHIQQQI") after 60 s
    146/148   run 3 — the two declared failures, nothing else
    152/154   run 4 — after the three harness fixes below, which add the
                       self-test's six checks: the two declared failures and
                       nothing else, out of a total that is now a function of
                       the cases

So the suite is **not flaky about `calcsize`**, and the two failures that do
happen are a REGISTERED, DOCUMENTED red: `formal-struct` carries

    expect='bugs/FORMAL_struct_pack_over_eight_arguments.md — a formal arm64
           call is limited to 8 register arguments, so struct.pack cannot be
           called for a format naming 8 values'

and that bug doc records the byte-identical transcript, `146/148 checks passed`
with the same two `pack(...) is refused, not wrong: build failed: … 9 arguments
exceeds the 8 …` lines. The original transcript was also internally
inconsistent — four `FAIL` lines against a `146/147` tally, which is one
failure — so it could not have been a verbatim capture.

**But the report was right that something is wrong, and it was the HARNESS.**
Three defects, all three real:

### 1. `build_and_run` threw `run.returncode` away

```python
    run = subprocess.run([out], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    return [ln for ln in run.stdout.split("\n") if ln.strip() != ""]
```

An image that builds, links, prints the right answer and then dies — SIGSEGV,
SIGBUS, a `dyld` kill — has the stdout a correct program has, so it was
compared and reported as a PASS. Measured, not argued, by re-running the
pre-fix pair against a real three-line image that prints `36` and returns 3:

    ok   a real image that exits 3 after printing 36   [length]
    ok   a real image that exits 3 after printing 36   [values]
    -> 2/2 checks PASSED for a process that exited 3

Fixed: `build_and_run` returns `(lines, how_it_died)`, and a negative
returncode is translated by `signal.Signals(-rc).name`, because `-11` in a
report names neither the signal nor the process.

### 2. `expect_lines` returned early, so the denominator depended on the verdicts

A case that failed on length cost ONE check and a case that passed cost two. The
original's 148/147/145/144 are exactly this: 0, 1, 3 and 4 failing `calcsize`
cases. A denominator that is a function of the failures is not a denominator,
and a suite whose total moves is a suite whose reader learns to re-run it — and
a re-run that comes back green is not evidence.

Fixed: two checks in EVERY outcome, the second saying `not reached: …` when it
could not be evaluated rather than being skipped, each with its own `what` so
"which of the two failed" is answerable.

### 3. A hung image abandoned the rest of the loop — the one that cost 21 checks

`subprocess.TimeoutExpired` is an `OSError`, not an `AssertionError`, so it
sailed straight through `expect_lines`'s `except AssertionError` and out of the
`for fmt in CORPUS_FORMATS` loop it was called from. **Every case after it was
never reached and nothing said so**: 122/127 where 148 was the number, with 21
checks silently missing from the tally.

Fixed: a run that does not finish raises `AssertionError` with the image's path
and what to do about it, which is what a build failure already was. The cases
after it now run.

## What was NOT the cause, measured

* **Not the program.** `calcsize("<8I")` and `calcsize("<HHIQQQI")` built and
  run 10/10 standalone in 0.00 s each, both printing the right answer, exit 0.
* **Not a codegen change on this branch.** The tree was the same for all six
  runs.
* **Not a shared content-addressed store.** The original's prime suspect was a
  racing `cas.publish` handing a reader a truncated artifact. It cannot:
  `cas.publish` writes a private temp, `fsync`s it and `os.replace`s it
  (cas.py:608), and the docstring says why — hash-named files are immutable, so
  a racing identical write is harmless. A truncated Mach-O is not available.
* **Not `discover_corpus_formats` moving.** `CORPUS_FORMATS` is computed once at
  import, and `test_the_corpus_was_discovered_and_is_not_empty` already asserts
  `len(CORPUS_FORMATS) >= 13` and names seven of them individually.

## The check that holds all of it there

`test_the_harness_records_a_case_even_when_it_cannot_pass`, in the file itself,
six checks, contributing a fixed number to the total (which is why the count is
154 and not 148, and why the two declared failures are still the only two). Four
of the six fail against the pre-fix harness, verified by restoring the old
`expect_lines` and the old `build_and_run` and re-running it:

    pre-fix expect_lines (early return):            1/6 pass, 5 FAIL
    …and the real-image probe reports a dead process as a PASS

Each probe records through a `probe()` helper that silences the tally and the
printing, because every case in the self-test is SUPPOSED to fail — a green run
that printed eight red lines from its own self-test would be the same noise this
doc is about, and five deliberately-red stub cases reaching the suite's total
would turn a green run red.

`RESULTS` also keeps the `detail` now, not just `(ok, what)`. A suite that
reports `FAIL <what>` and discards the only sentence that says why has discarded
the evidence, and `-v` prints it.

## Related

* `formal-struct`'s registration comment carries the same measurement and the
  reason the job is in `proofs` rather than `check` (43 s alone, 201 s beside
  the other seven, 154 checks most of them a build).
* `bugs/CODEGEN_ab_native_fails.md` §4's cost table says "2 of 154 cases" for
  the same reason, and `CLAUDE.md`'s `EXPECTED` table with it.