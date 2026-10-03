# Project Conventions

## Git safety — NEVER discard work with `git checkout`
`git checkout -- <file>` (and `git restore <file>`) permanently destroys
uncommitted changes with no recovery. This has already destroyed ~10 hours of
work in this project. Rules:

- Do NOT use `git checkout <path>` / `git restore <path>` to "reset" a file
  unless you are certain every uncommitted change in it is regenerable
  (e.g. produced by a script you can re-run) AND you have re-read the diff
  immediately beforehand (`git diff <path>`).
- When iterating on generated files, prefer `git stash push -- <paths>`
  (recoverable via `git stash pop`) over checkout, or have the generating
  tool write to the file only after all validation passes.
- `git checkout <branch>` is safe for committed state; the hazard is
  path-scoped checkout/restore against uncommitted edits.
- Before ANY checkout, run `git status --short` and eyeball what would be
  discarded.

## Code Quality
- Never pick the simple/quick fix. Always pick the production-quality approach.
- Consolidate duplicates rather than maintaining parallel implementations.
- If two files do the same thing, merge them — don't symlink, don't copy-paste.

## AST Nodes
- `fire_compiler.py` is the single source of truth for all AST node definitions.
  (It was `mojo_compiler.py` until the 2026-09-26 rename; that file no longer
  exists, and any doc still naming it is stale.)
- `myinterpreter.py` imports AST nodes as `import fire_compiler as N`, and so
  does every module in `mojo/middle/` and `mojo/backend_gimple/`. The middle
  tier re-exports them with `from mojo.middle.types import *` /
  `from mojo.middle.types import IdentExpr, ...` and reaches them as
  `gimple_ctypes.FunctionDef` etc. — that re-export is deliberate (it is what
  lets the self-hosted compiled path see real node classes instead of boxed
  values), so do not "tidy" those call sites back to a direct import.
- `ast_nodes.py` is dead and should not exist.

## Bug-fixing sessions — no time-boxing, no re-verify-and-stop, amortize the gate
When asked to work through a batch of bugs (from `bugs/`, `bugs/hard/`, or
anywhere else), these rules override any instinct to move on quickly:

- **No per-bug time limit.** Do not budget "~30-45 minutes then move to the
  next one" or any similar clock. A problem takes what it takes — 2 minutes
  or 2 hours or 2 days. Time-boxing a hard bug produces exactly the failure
  mode this rule exists to stop: stopping right as real progress was about
  to happen, then writing up the stop as if it were a considered conclusion.
- **Never spend a turn just re-verifying/re-confirming a bug's existing
  Status entry and stopping there.** A doc with many "re-verified unchanged"
  entries is a sign PAST sessions did this — it is not proof the bug is
  unfixable, and re-doing that same non-fix one more time is pure token
  burn with zero output. For every bug you touch, either (a) land a real
  fix, (b) land real partial forward progress and say so honestly (see
  below), or (c) don't start on it this session — there is no fourth
  option where you spend effort and produce a fresh "confirmed still
  broken" paragraph with no code change.
- **Partial progress counts, and should be checked in.** If a bug is
  genuinely large, it's fine to land 30% of it — real scaffolding,
  interpreter/codegen groundwork, a data model, whatever moves the actual
  implementation forward — commit that, and update the bug doc's Status
  section to describe exactly what landed and what's still missing, rather
  than reverting because "it doesn't fully close the bug." Shared
  infrastructure that several bugs need (feature X/Y/Z) but that by itself
  fixes none of them is equally worth checking in on its own, noted as
  infrastructure rather than as a fix for any specific doc.
- **Stop and report only when truly stalled** — no viable next step, not
  merely "this will take a while." At that point, stop, explain concretely
  what's blocking forward progress, and let the user decide (pick a
  different angle, accept it as a real feature project, or hand it to a
  more capable model). Do not manufacture a stopping point at a fixed
  effort level.
- **Batch bugs specifically to amortize the quality gate below**, not to
  cap total effort. The full gate (steps 0-4) is the expensive part in
  TOKEN terms (not wall-clock/CPU, which is free to spend) — running it
  after every single small fix wastes tokens re-deriving the same green
  result. Group related fixes and run the full gate once per group and
  once at the end, per the batching guidance already in that section.
- **No mid-batch check-ins and no mid-batch gate runs.** While working
  through a batch, do not stop to summarize progress, ask "should I keep
  going?", or run any gate step (make check, compile_stdlib.py, bootstrap,
  etc.) as a status check between fixes. Land the whole batch of intended
  work first; run the full gate exactly once, at the end, covering
  everything accumulated. Explicitly requested by the user 2026-09-13 —
  interim gate runs and interim check-ins were seen as wasted tokens/time
  when the intent was always to gate once at the end anyway.

## Running the checks — one runner, named buckets
`tools/suite.py` runs everything: the buckets, each test's driver, the memory
ceilings, the ordering, and one pass/fail count. The Makefile's targets are
one-line recipes that call it, so `make check-<x>` and
`python3 tools/suite.py <x>` are the same thing.

    make check              # the everyday SUBSET of the gate, -j ncpu, one tally
    make gate               # THE gate: check plus coro/stdlib/native/bootstrap
    make bootstrap          # just the 3-stage self-host chain
    gmake -j1 check         # strictly serial, every job's output streamed live
    make check J=4          # 4 at a time (works with either make; Apple's 3.81
                            # cannot express -j1 from inside a recipe)
    make check-list         # the registry: bucket, driver, memclass, deps
    make check-plan         # the plan and its ordering, run nothing
    python3 tools/suite.py -j1 --list     # the same, without Make

`check` is a strict subset of `gate`, so `make check && make gate` is the
same work twice — see the gate section. Pick one per intent: `check` while
iterating, `gate` once at the end.

Reading a run: the screen shows only failures, skips, a resource breach, a
30-second heartbeat, and the final tally. **Everything else — a PASS line per
job with its full argv, exit code, duration and measured peak, the complete
output of anything that failed, the reason for every skip, and the
environment (git HEAD, dirty count, gcc, jobs, MEMLIMIT_GB) — goes to
`build/suite.log`.** A RESOURCE verdict is reported separately from a failure
on purpose: memcap killed the process for memory before it finished, so it
says nothing about whether the output was right.

The tally counts **every** test exactly once, and that is enforced rather than
hoped for: the summary, the screen sections and the exit code are rendered
from one table (`suite.TALLY`), the runner refuses to start if a status it can
produce has no row in it, and a summary whose counters do not add up to the
test count says so on the screen and exits non-zero. So add the numbers up and
they must equal the `N tests` in the tail. A hang is a failure in its own
class: it is listed under `FAILED:` tagged `[TIMEOUT]`, and it is not one a
`expect=` marker can forgive — a job killed at its timeout has reported
nothing, so letting a marker absorb it would be a way to not run a test and
call the run green.

Memory: two mechanisms, and the second is the one that bounds the machine.

A **ceiling** is per process tree: every job that runs a `mojoc` binary, or a
whole-closure compile standing in for one, is capped by `tools/memcap.py` at
the ceiling its `memclass` names (`tiny` 4 GB, `small` 8, `module` 24,
`program` 55, `stage` 96 — see the `MEMCLASS` table in `tools/suite.py` for
which is which). **Each class is assigned from the job's MEASURED peak**
(`MEASURED_PEAK_GB`, read off a real run's log by the same wrapper that does
the killing), never from the shape of the workload it resembles, and a class
over 4 GB carries a one-line `memwhy` pointing at
`bugs/PERF_memory_over_4gb_is_a_bug.md` — over 4 GB is a debt, not a fact.
`python3 tools/suite.py --list` prints peak, class, ceiling and ratio per job,
plus the over-provisioned (>8x) and unmeasured lists. `MEMLIMIT_GB=96` raises
every ceiling and is also the answer to a class that no longer fits;
`MEMLIMIT_GB=0` removes them all and says so loudly.

A **reservation** is per machine, and it is not optional. A ceiling bounds one
tree and says nothing about how many may run at once, which is not a bound at
all: on 2026-09-29 about thirty compiler processes at 30-43 GB each, every one
of them inside its own ceiling, collapsed the box. So every job takes its
memclass out of ONE machine-wide budget (`tools/memslot.py`, strict FIFO,
`~/.gmojo/memslot`, `MEMSLOT_BUDGET_GB`, default 96) *before* it is spawned,
and gives it back when it exits — so "18 x 4 GB" means 24 at a time, and
the count includes the other worktrees and your own terminal. That is also why
the classes are measured: a class is a claim on the machine, so one that is 20x
the job's peak is not a margin, it is twenty other jobs that cannot run. An
`excl` job reserves its class like any other and is additionally alone in ITS
run — `excl` is about jobs racing on a shared artifact, not about memory, and
a class over half the budget already means alone on the machine by arithmetic.
A reservation covers the tree it admitted, which is why the
`$(call memslot,…)` recipe in the Makefile does not deadlock against the
runner's own admission of that recipe (`MEMSLOT_HELD`, and
`memslot.covering`) — and why a recipe's class may never exceed the class of
the job that runs it, which `test_suite.py` checks.

A job's TIMEOUT starts after admission, never during the queue wait: a `stage`
job can wait a long time for 96 GB on a busy machine, and a timeout that
counted the queue would kill jobs that had done nothing wrong.

Cached results, and what is deliberately **not** cached. Three caches, with
different jobs:

- A check whose inputs are unchanged replays its recorded PASS
  (`checked_run.py`, content-addressed). A recorded FAILURE is re-run — the
  key covers the files named in the test's `extra` list, not a stale
  `build/`, a leftover module-cache dir, or the machine, and a cached red that
  no fix can clear is worse than spending the time to find out.
- A step whose artifact is a **binary** — `mojoc`, `stage2/mojo` — is cached
  by the content of its real inputs (the closure, via
  `cas.selfhost_fingerprint()`, plus the exact argv), which is what makes
  `make native`/`make gate` cheap to re-run. A hit is announced on the screen
  and the step does not run at all; `--no-cache` forces it and still
  publishes. Note that `selfhost_fingerprint()` is a *different, larger*
  input set than `compiler_fingerprint()`: the latter deliberately omits
  `fire.py`/`fire_main.py`/`myinterpreter.py` because no stdlib module's
  codegen reads them, which makes it UNSOUND as a key for anything that
  compiles the compiler. `test_suite.py` walks `fire.py`'s import closure and
  fails if anything reachable is unhashed, because that failure mode is a
  wrong binary served from cache, silently.
- The three stage trees are **never** cached. `verify`'s entire job is
  comparing stage1 against stage2 against stage3, so caching two of the three
  would make its comparison a fresh artifact against a copy of itself — the
  gate would pass by construction and stop detecting the byte-identity
  divergence it exists to detect. Do not "fix" this by adding a cache; if
  bootstrap is too slow, fix the memory blowup
  (`bugs/CODEGEN_bootstrap_resource_blowup.md`), which is the actual cause.
  For scale: the 45-file per-stage sweeps measure **1.8 s** in total, so all
  of bootstrap's ~32 minutes is the three whole-closure dumps plus the
  `gcc -O0` compile between them. Per-file caching would buy nothing.

## The quality gate — one command: `make gate`

    make gate          # THE gate. == python3 tools/suite.py gate
    make check         # a strict SUBSET of gate (see below) — for the
                       # everyday inner loop, not as a second opinion

**`gate` is a bucket, and `tools/suite.py`'s registry is its only
definition.** Do not restate its membership in this file. The list used to
live here as a hand-maintained six-step enumeration and it drifted — it went
on claiming things about `bootstrap`/`check-native-dumpfull` that stopped
being true while still reading as current. `python3 tools/suite.py --list`
(or `make check-list`) is the answer, and it cannot go stale.

`check` ⊂ `gate`: the `gate` bucket contains the whole `check` bucket plus
`coro`, `stdlib`, `native` and `bootstrap`. **Running `check` and then
`gate` is duplicated work, not belt-and-braces** — the second run replays
the first from cache and tells you nothing new. Run `check` while iterating;
run `gate` once, at the end, over everything that has accumulated.

### Before considering a compiled-path change done

Anything touching `fire_compiler.py` (the shared parser/AST),
`gimple_codegen.py`, `module_loader.py`, `mojo/backend_gimple/*` or
`mojo/middle/*` — including subagent work — owes a full `make gate`. This is
not "extra"; it is the definition of done for that class of change. A change
passing `test_gimple.py`/`test_module_cache.py`/`selfhost` alone is NOT
sufficient evidence the compiled path is unaffected, and the reason is
structural rather than a matter of testing harder:

- `gimple_codegen.py`'s lowering of an AST node shape is a separate,
  independently-maintained implementation from `myinterpreter.py`'s
  evaluator, so a parser change can be invisible to the interpreter suites
  and still break the compiled path. Real: a fix that wrapped `*`/`**` call
  arguments in a `UnaryOp` fixed the interpreter and broke
  `gimple_codegen.py`'s own self-compilation, with both suites green
  throughout.
- Almost every step drives codegen through the python3-interpreted
  reference. Only `mojoc`/`ab-native`/`native-dumpfull` and `bootstrap`'s
  `stage2`/`stage3` exercise the self-hosted **binary's** own compiled
  codegen. A native-codegen-only bug can produce a wrong-but-exit-0 artifact
  that every other step is structurally blind to — real 2026-08-13→09-13,
  where silencing a known SIGBUS silently dropped two compiled sibling
  modules (a 1.4M-line diff from correct) while every other check stayed
  green.
- `linkmode` alone covers the real `driver.compile_program` link-mode
  pipeline `fire.py build` uses by default; every other step, plus
  `compile_stdlib.py` and `build_stdlib_dylib.py`, goes through the
  single-translation-unit `do_imports=False` inline path. A link-mode-only
  module/import-registration bug is invisible to all of them.
- `stdlib-dylib` + `stdlib-syntax` are the only steps that exercise the
  breadth of real Mojo source this compiler must keep working (664 files).

### Two gate verdicts need judgement, not just a zero exit code

`make gate` passing is necessary, not sufficient, on these two — both fail
*silently* by design and neither shows up as a non-zero exit:

- **`stdlib-dylib`**: compare the `skip <module>:` count before/after. It
  must not increase. A type-resolution change can regress dozens of real
  stdlib modules from clean-compiling to falling back to source, and the
  documented "skip and fall back" stopgap absorbs it without failing
  anything. If it increases, bisect the responsible type/symbol first.
- **`stdlib-syntax`** (`compile_stdlib.py`): compare
  `FAILED: N (E expected, U unexpected)` before/after — `U` must not
  increase. A file that is a genuine out-of-reach gap belongs in
  `EXPECTED_FAILURES` at the top of `compile_stdlib.py` with a comment
  saying why, never silently ignored.

For a change that is *supposed* to be behaviour-preserving (a pure
performance fix, a refactor), the standard is stronger than a green gate:
**byte-identical generated C** on a large succeeding case, before vs after.
`cmp` the artifacts. Anything less is a change you have not finished
verifying.

## Shared expensive dependencies: build once, then depend on it

A step whose product every other step needs must be its own registered test
with `deps`, not something each consumer races to produce. Two mechanisms
cooperate, and the pattern generalises:

- **In the process** (`formal/lean.py`'s `ensure_library` is the worked
  example): a check-then-act on a shared filesystem is a cache stampede
  waiting to happen. `lib/ProofLib.olean` is 27MB and ~80s, every
  proof-checking path calls `ensure_library`, and the proofs bucket runs 16
  such paths at once. Before the lock, 3 concurrent callers meant 3
  simultaneous `lean -o` invocations on the SAME output path — measured, all
  ~81s — which wastes ~16 CPUs and can interleave into a truncated `.olean`
  that every later typecheck then reads. So the build takes an exclusive
  `flock` (kernel-released on process death, so a killed run cannot wedge
  the next one), re-checks currency *inside* the lock, and writes via a
  private temp + `os.replace`. Measured after: 8 concurrent callers → 1
  build, 7 no-ops.
- **In the runner**: the lock makes latecomers *queue*, not vanish, so the
  library is also registered as its own step (`prooflib`) that every
  proof-checking test `deps` on. One build happens, alone, before the
  fan-out is released; the rest then find the stamp valid and return in
  ~0.1s. `prooflib` is deliberately in no bucket — it is a dependency, not a
  test, and `make check`/`make gate` must not pay for it.

Note what is deliberately NOT there: a suite-level artifact cache for it.
The `.olean` is already content-addressed twice over (the cas publish inside
`ensure_library`, and the `.srcsha256` stamp that makes a repeat run a stat
rather than a hash), so a third cache in front of two working ones would
only add a way to go stale — notably when one cas is shared between
checkouts.

## Known-failing tests: recorded, not hidden

A test registered with `expect='<why>'` in `tools/suite.py` is a known
failure. It reports as `EXPECTED` with its reason on screen, in the tally,
and in `--list`, and it does not fail the run. The reason string is
mandatory — a marker without one is a silenced test. **What running it costs
decides whether `expect=` is the right marker at all: a known failure too
expensive to run gets `disabled=<bug doc>` instead, which is the subject of
the next section.**

The anti-rot half is the point: an `expect`-marked test that **passes** is
reported as a **FAILURE** ("marked expect=… but it PASSES — drop the
marker"). A marker nobody revisits is a bug quietly reintroduced, which is
the same reasoning that makes `checked_run.py` re-run a recorded failure
instead of replaying it. Forgives only `FAIL`/`ERROR` — never `RESOURCE`
(a memory ceiling is a fact about the machine, and swallowing it would hide
exactly what the caps exist to catch) and never a dep-induced `SKIP`.

Prefer fixing over marking. A stale test that references a renamed file is
not a known bug, it is a hole in coverage: `coro` sat in the gate naming
`mojo_*` runtime files after they were renamed to `fire_*`, so all 20 of its
cases had been failing to compile and the suite had been reporting 0/20
since the rename. Nothing was expected, nothing was reported, and the
coroutine runtime was untested. Fix the test; if a subject really is broken,
mark it with a reason and a bug-doc link.
- `test_runtime_diff.py` compares the two **engines** with each other, which
  structurally cannot catch a bug they SHARE. `test_interp_oracle.py`
  (`interporacle`) closes that: it runs each program through both
  `python3 fire.py run` and `python3` on the *same* text and requires
  identical stdout and exit code. Two real interpreter bugs went unnoticed for
  exactly that reason — a `@classmethod`'s `cls` binding the first real
  ARGUMENT, and `@deco` being parsed and then never applied at all (the
  compiled path ignored decorators too, so the diff was clean). A new
  interpreter-oracle bug belongs there, not in `test_runtime_diff.py`.

Current `EXPECTED` entries, and the one `DISABLED` entry. **`python3
tools/suite.py --list` is the census**, not this table — and since 2026-10-01 it
is the only census that can be: every registered test is now in a bucket unless
it declares `dep=True` (one does, `prooflib`), which `test_suite.py` checks in
both directions. So the `[]` column the eleven ungated `expect=` jobs used to
print cannot be produced again by accident, which is what
`bugs/TEST_expect_marked_tests_in_no_bucket_never_run.md` and
`bugs/TEST_registered_tests_in_no_bucket_never_run.md` were about; both docs are
deleted with their fixes.

A marker that states a count is CHECKED against the run, for the same reason:
`expect=` forgives `FAIL`/`ERROR` wholesale, so a new failure inside an
already-marked test used to be absorbed silently and the tally still said
EXPECTED. The count is read out of the marker's own leading prose ("3 of 14:",
"36 failing:") and out of the harness's summary line, and a disagreement is a
FAILURE — the same signal as a marker whose test starts passing, because both
mean the marker no longer describes the test. A marker that describes a
whole-job condition rather than a set of cases states no count, and one that
states a count but whose run prints none is reported as UNCHECKED rather than
agreed with; which markers are in which class is `--list`'s to say, not a list
restated here.

`formal-toplevel` was the fourth formal host-module row this table used to
carry and, like `formal-struct` before it, lost its `expect=` on 2026-10-02:
both failures each named were rewrites of an assertion that could no longer see
the case it was watching, and the cases are now build-and-RUN comparisons
against CPython. The remaining `expect=` jobs besides the two heavyweight steps
and the formal host-module rows are the compiled-path async/await cluster, all
cheap (0.0-0.2 GB, 1.2-11.6 s each) and all in `coroutine` and `x86`, each
measured one at a time before being named, with the measurement at its
registration. `bugs/CODEGEN_ab_native_fails.md` §4 carries the full inventory
and the reasoning for `expect=` rather than `disabled=` on each.

| test | marker | subject | cost it charges every gate |
|---|---|---|---|
| `ab-native` | `disabled=bugs/CODEGEN_ab_native_fails.md` | python vs native codegen over the A/B corpus | **nothing** — registered, not run |
| `native-dumpfull` | `expect=` (`SELFHOST_TOKENIZE_BLOWUP`) | the native `--dump-full` artifact vs the reference | 31.3 GB, `program` (55 GB) |
| `bootstrap-stage2-dumps` | `expect=` (`SELFHOST_STAGE2_STALL`) | the compiled binary dumping every source | 47 items x 0.5 GB, `tiny` (4 GB) each |
| the async/coroutine ones | `expect=`, count checked | compiled-path async/await, coroutine and closure capture | 1.4-15.4 s each, `tiny`; `coroutine` |

`formal-toplevel` and `formal-module-attr` were in this table and are not any
more: both markers were dropped on this tree, so `--list` reports neither and a
row claiming otherwise is the failure `test_suite.py`'s
`a stated test status must match the registry` exists to catch. It is a census
(`python3 tools/suite.py --list`), not this file.

**A declared red and an unrun red are different failures**, and the second is
worse: a marker on a test no gate runs can never be observed going green, so it
cannot rot out. That is why the ungated ones above were a coverage hole
(`bugs/TEST_expect_marked_tests_in_no_bucket_never_run.md`, and
`bugs/TEST_registered_tests_in_no_bucket_never_run.md` for the ungated tests
that are not marked at all) and not merely a cost question, why they went into
`coroutine` rather than staying out of every bucket, and why "register it" is
never the same act as "run it". Every one of them is in a bucket (2026-10-01),
measured one at a time before being named, and `test_suite.py`'s `the buckets:`
checks are what keeps it that way — a registration that is in no bucket fails
the self-test unless it declares `dep=True`, which is `prooflib` and nothing
else.

The two heavyweight `expect=` entries are the old "the binary segfaults on any
input" claim, which was **measured false on 2026-09-27 and corrected rather than
left to rot**: `./mojoc --dump-full` on a two-line program is now exit 0 / 12.1 MB
/ 94.6 M instructions. What is left is the self-hosting bootstrap pre-pass's cost
(~15-30 GB / ~15-25 s per call, localised in
`bugs/CODEGEN_bootstrap_resource_blowup.md` and BLOW.md §0) and, for
`bootstrap-stage2-dumps`, a silent-wrong-answer `mojo_unsupported_iter` class
that no exit code reports. Divergences themselves:
`bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`.

**The gate is otherwise clean, and deliberately no file here says how many.**
Every `expect=` and `disabled=` registration in the registry is accounted for
above and there is no undeclared red — that is a statement about the REGISTRY,
not about a run. A tally, by contrast, is a claim about a *run*, and a run is
not a property of the tree: it goes stale underneath a change made in none of
the files that state it. This sentence has been the third file to be caught
that way (it read "`check` 11/11, `coro` 20/20, `stdlib` 2/2" when the bucket
held 21 names, then again when it held 22, then again when it held 36), which
is the argument for removing the number rather than for refreshing it. The
current figures are the last line of `build/suite.log`; a bucket's SIZE is
`make check-plan` / `python3 tools/suite.py --dry-run <bucket>`, which reads
the registry and is therefore a fact about the tree rather than about a run.
A doc that states a test's STATUS is checked against the registry by
`test_suite.py`, and `tools/dangling_doc_refs.py` walks the citations;
`bugs/DOCS_stated_test_statuses_the_registry_no_longer_has.md` is deleted with
its fix. A doc that states a tally is not checked, because there is nothing to
check it against until somebody runs the gate.

## Known failures: `expect=` or `disabled=`, decided by cost

Two markers for the same state of knowledge — *this test is red and we know
why* — and the only thing that decides between them is what running it costs.

1. **A known failure that is CHEAP runs, with `expect='<why>'`.** Its anti-rot
   is the whole reason it is worth running: an expected-fail that starts
   passing is reported as a FAILURE. A cheap test can afford to keep that
   check alive every gate.
2. **A known failure that is EXPENSIVE must not be run: `disabled='bugs/<doc>.md'`.**
   Registered, never run — no process, no memcap, no reservation, no wall time
   — reported as its own `DISABLED` status with the doc, counted in the tally,
   listed on screen and in `--list` and `--dry-run`, and it reserves **0** from
   the memslot ledger whatever class it carries. **The threshold is the
   3-4 GB memory standard in `bugs/PERF_memory_over_4gb_is_a_bug.md`**, applied
   to time as well: a class over that line is a debt, so a job carrying one is
   too expensive to spend on a known answer; so is one that takes more than a
   few minutes. Measured, not guessed — `ab-native` was `expect=` while using
   20.5 GB and holding 55 of the machine's 96 GB, exclusive, every gate.
3. **Never spend an exclusive, machine-sized reservation on a job whose outcome
   is already known.** `excl` and a `program` class are for jobs that must
   finish; on a job that cannot pass yet, they are the machine paying twice.

**The bug doc IS the switch, and that is what makes this safe.** The rule
below says a fully fixed bug's doc is DELETED, so the doc's disappearance is
exactly the event "the bug is fixed": `tools/suite.py` refuses to load the
registry while a disabled test's doc is gone, naming the test and saying to turn
it back on. A doc that never existed (a typo) fails the same way with its own
message, and a job carrying both markers is refused outright. So a fix cannot
land without re-enabling its test, and a disabled test cannot stay off
forever. Checked in `test_suite.py` (`the disabled markers in the registry are
honest`) and enforced at import.

## Bug docs

`bugs/` is a queue of work, not an archive. **A doc for a bug that is fully
fixed is deleted, not left behind with a Status history** — a fixed bug
still listed is indistinguishable from an open one to whoever reads the
queue next, and the accumulated "re-verified unchanged" entries are worse
than no entry: they cost a future session real time to re-derive and change
nothing. When a fix lands, remove the doc in the same commit.

What earns a doc instead is a bug that is fixed-but-not-verified, partially
fixed with the remainder written down, or not fixed at all. Those are the
cases where a Status section carrying the evidence and the exact next step
is worth more than the absence of a file. `bugs/hard/` is for the ones that
need their own careful pass; `bugs/OPEN_WORK.md` is the triage index.
