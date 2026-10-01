# CODEGEN_test_struct_formal: the struct suite is FLAKY, and its own harness cannot say why

**Found 2026-09-30 while running the regression floor after five unrelated
fixes. NOT MINE and NOT FIXED** — `struct` and its formal lowering are another
worker's area, and this is a test-harness defect as much as anything else.
Filed because `struct-formal` is a REGISTERED gate job, a red run of it is
indistinguishable from a real regression, and a suite whose pass count changes
from run to run on an unchanged tree is worse than no suite.

## What I ran, and what I saw

Four consecutive runs of the same tree, nothing changed between them:

```console
$ python3 test_struct_formal.py     # run 1
148/148 checks passed
$ python3 test_struct_formal.py     # run 2
FAIL calcsize("<4sBBBBBBB5x") == 16 (every corpus format is implemented):
     expected 1 numbers, program printed 0: []
FAIL calcsize("<8I") == 32 (every corpus format is implemented): …
FAIL calcsize("<HHHHHH") == 12 (every corpus format is implemented): …
FAIL calcsize("<HHIQQQI") == 36 (every corpus format is implemented): …
146/147 checks passed
$ python3 test_struct_formal.py     # run 3
142/145 checks passed
$ python3 test_struct_formal.py     # run 4
FAIL … (the same four, plus more)
140/144 checks passed
```

**The total itself moves — 144, 145, 147, 148 checks — on an unchanged tree.**
That is the finding. A count that changes run to run means the number of checks
REACHED changes, not just their verdicts, so the failure is not "the struct
lowering computes a wrong size"; it is "some checks did not run, or ran twice".

Every failure is a `calcsize` case, and every one has the same shape: **the
build SUCCEEDED and the image printed nothing.** `build_and_run` raises
`AssertionError` on a non-zero build, and `expect_lines` catches that and reports
`build failed: …`, so a build failure is distinguishable in the output. These
are not build failures. They are images that ran and produced no stdout.

## The harness defect, which is what makes this unattributable

`test_struct_formal.py`'s `build_and_run`:

```python
run = subprocess.run([out], capture_output=True, text=True,
                     timeout=RUN_TIMEOUT)
return [ln for ln in run.stdout.split("\n") if ln.strip() != ""]
```

**`run.returncode` is never read.** A program that builds, links, and then dies
at the first instruction — SIGSEGV, SIGBUS, an illegal instruction, a `dyld`
kill — returns an empty stdout, which is indistinguishable here from a program
that legitimately printed nothing. So the one piece of evidence that would say
*crashed* instead of *printed nothing* is thrown away, and the reported failure
points at the struct tables when the real answer is a process that died.

That is a one-line fix and it is the first thing to do, because it converts an
unattributable flake into an attributable one. Every other thing here is a
hypothesis until that is in.

## What is NOT the cause, measured

* **Not the program.** `calcsize("<8I")` standalone, built and run 8 times, and
  then all four failing formats 3 times each through the same `fire.py build
  --formal` path (12 builds, 12 correct answers, 12 clean exits):

  ```console
  $ for i in 1..8; do .tmp/w/cs8i.bin; echo "exit=$?"; done
  32 / exit=0     (×8, all printing 32)
  ```
* **Not a codegen change on this branch.** The suite was run on the same tree
  before and after each of this branch's five commits; it was green
  (148/148) on some runs of every one of them. The failures appear on runs with
  no code change at all.
* **Not the machine's memory budget.** Every one of these runs was inside
  `tools/memslot.py --gb 8`, so memory admission is not the variable.

## The next step, in order

1. **Check `run.returncode`.** One line in `build_and_run`. Re-run the suite in a
   loop until it goes red and read what it says. Everything below is a guess
   until this is done.
2. **Reproduce under the conditions where it happens.** The machine had ~15
   parallel workers running. `memslot` serializes the memory RESERVATION and
   nothing else, so N builds can be in flight at once. Loop the suite with and
   without concurrent load; if it only fails under load, it is a timing or
   contention bug and not a language one.
3. **The prime suspect is the shared content-addressed store.**
   `~/.gmojo/cas` is one directory shared by every worktree on this machine, and
   `formal/lean.py`'s `ensure_library` documents the exact hazard this project
   has already been bitten by: three concurrent callers meant three
   simultaneous writes to ONE output path, which "can interleave into a
   truncated `.olean` that every later typecheck then reads". The fix there was
   an exclusive `flock` plus a private temp and `os.replace`. If a build here
   publishes its image through the same store, a reader can be handed a
   truncated artifact — and a truncated Mach-O that still has a valid enough
   header to load, and then dies, is exactly "builds, runs, prints nothing".
   Worth checking whether `cas.publish` for a build artifact is atomic.
4. **If it is not the store, bisect the suite itself.** The check COUNT moves, so
   something is being reached a variable number of times. `CORPUS_FORMATS` is
   computed once at import by `discover_corpus_formats()`, which globs
   `formal/*.py` and `test_x86_64_decode.py` for format strings and keeps the
   ones CPython accepts. If that walk's result varies — a partially written
   `.py` in `formal/` from a concurrent editor, or a `__pycache__` entry — the
   corpus and therefore the number of checks moves with it. Print
   `len(CORPUS_FORMATS)` at the start of every run and see whether THAT moves;
   it is a one-line diagnostic and it splits (4) from everything above in a
   single run.

## Why the owner should care more than "a flaky test"

`struct-formal` is in the gate, and this suite is the only thing that
differential-tests the `struct` module's formatting against CPython for every
format the corpus uses — `test_every_corpus_format_is_implemented` is the check
that would have caught `<II` being missing, and a format the table does not know
returns 0, which is a plausible-looking answer rather than an error. A suite
whose pass count moves on an unchanged tree trains its reader to re-run it, and
a re-run that comes back green is not evidence. That is the same failure the
project already records for the interpreter oracle in `test_interp_oracle.py`:
a test that cannot fail reliably cannot be evidence when it passes.
