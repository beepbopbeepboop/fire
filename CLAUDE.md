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

Memory: every job that runs a `mojoc` binary, or a whole-closure compile
standing in for one, is capped by `tools/memcap.py` at the ceiling its
`memclass` names (`small` 8 GB, `module` 24, `program` 55, `stage` 96 — see
the `MEMCLASS` table in `tools/suite.py` for which is which and the
measurements behind them). `program` and `stage` are the ones known to pass
10 GB, and they are exclusive: the runner gives them the machine to
themselves and starts nothing else until they are done, so a 55 GB job is
safe to leave running unattended. `MEMLIMIT_GB=96` raises every ceiling;
`MEMLIMIT_GB=0` removes them all and says so loudly.

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
mandatory — a marker without one is a silenced test.

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

Current `EXPECTED` entries, all one root cause — the self-hosted binary
segfaults on any input, including a two-line program (`./mojoc --dump-full`
exits 139), so these three are red together and are fixed together:

| test | subject |
|---|---|
| `ab-native` | python vs native codegen over the A/B corpus |
| `native-dumpfull` | the native `--dump-full` artifact vs the reference |
| `bootstrap-stage2-dumps` | the compiled binary dumping every source |

Tracked in `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`. They
flip themselves to FAIL the moment the binary stops crashing, which is the
intended way for them to be retired.

**The gate is otherwise clean**: `check` 11/11, `coro` 20/20, `stdlib` 2/2,
`mojoc` builds, `bootstrap` green through `stage2-cc`.

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
