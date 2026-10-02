# UNTESTED: what the test estate does not test, measured

Agent [5] of the five-agent round of 2026-09-28, `FORMAL.md` §11.2 — *"the
test estate: what is not tested, and the machinery that would know"*.

Everything below was measured on this tree by running things, not by reading
bug docs. Where a number came from a re-run rather than a source, the re-run is
named. The list is not an archive: §1 is the shape, §2 is the ordered inventory,
§3 is the three findings worth acting on, and §4 is what was pinned.

**The short version.** 81 `test_*.py` files, 33 named by a registered test, **50
named by nothing**. **21 of those 50 exit non-zero** — 4 of them at *import*,
naming source files that no longer exist. 12 of the 20 cached specs rest on a
cache whose asymmetry had never been executed by any test. And the check that
`test_suite.py` walks `fire.py`'s import closure to keep honest has no
equivalent for the 45 example files a cached test is *about*.

---

## Status, 2026-10-02 (this pass — §3.2's four dead-at-import tests are closed, one of them by becoming real coverage)

§3.2 said four tests die at import naming `mojo/ast_nodes.mojo` and
`mojo/parser.mojo`, neither of which exists, and called that "the `coro`
failure verbatim, from CLAUDE.md: the same class, four more files, and the
`coro` one was found by accident". All four are now closed.

**Three were deleted**, with their `UNREGISTERED` excuses, because there was
nothing to repair: `mojo/` has no `.mojo` files at all (the tokenizer and
parser became `fire_compiler.py`, `ast_nodes` was deleted outright), so
`test_myinterpreter_simple.py`, `test_phase2_parser.py` and
`test_phase2_parser_simple.py` could only ever have asserted something about
files that do not exist. §3.2's Tier 3 said deletion is the defensible option
and named the reason — "a test of a module that no longer exists is not a slow
test, it is a wrong claim" — and `test_myinterpreter.py` already runs the
interpreter end to end and passes, so nothing was lost with them. One of the
three additionally **exited 0 while printing `✗ Failed to load modules`**, so
they were also three instances of §3.3.

**The fourth was repaired, and it is the one worth having.** §3.2's own words:
"`test_myinterpreter_validation.py` is the expensive one to delete — it
validates the interpreter's output against Python's own tokenizer, and that
check is worth having *somewhere*. It is the strongest cheap parity check in
the tree and nothing runs it." It now exists and runs.

It compares `fire_compiler.py`'s `py_tokenize` with ITSELF, reached two ways:
imported directly, and reached **through `myinterpreter.py`'s `Interpreter`
executing `fire_compiler.py`'s own source** — built exactly the way `fire.py
run` builds every program it interprets, so the function under test is the
interpreter's own rendering of that code and not a re-import. The corpus grew
from eight hand-written snippets to **67 texts: 18 snippets plus 49 whole real
files** (every `formal/examples/*.mojo`, `fire_compiler.py`,
`myinterpreter.py`, `gimple_codegen.py`, `version.py`), because a tokenizer's
hard cases are the ones a snippet never reaches.

It is the only check of its kind, and §3.2 explains why that matters: an
interpreter bug produces a wrong ANSWER rather than an exception, so the
compiled path ends up wrong in the same direction and every engine-vs-engine
diff in the tree stays clean. That is how `@classmethod`'s `cls` binding the
first real ARGUMENT, and `@deco` being parsed and then never applied at all,
stayed invisible.

**It found a bug on its first run**, which is the argument for the whole
exercise: 66 of 67 matched and the 67th raised `NameError: name 'SyntaxError'
is not defined`. `myinterpreter.py`'s scope defined `Exception`, `ValueError`,
`TypeError`, `RuntimeError`, `KeyboardInterrupt`, `EOFError` and
`StopIteration` — and **not `SyntaxError`**, which `fire_compiler.py` raises
from five sites. So the interpreter's copy of the tokenizer could not REPORT a
lex error, which is the one thing a tokenizer has to be able to do. Fixed by
defining the rest of the standard exception hierarchy; the 24 names are now in
scope.

The comparison also had to grow a second half for that to be visible: it
compares what each route **did**, not only what it returned, so two routes that
both raise must raise the same exception TYPE and the same message. A compare
that returned "both raised" would have reported 67/67 on the day the
interpreter's scope had no `SyntaxError` in it — which is §3.3's shape one
level down, a swallowed exception.

Registered as `interp-tokenizer-oracle` in `check`/`gate`, `mem='tiny'` from a
measured 0.1 GB, `extra` naming both subjects rather than just the test (the
oracle is "the same function through two engines", so a change to either side
is an input), 67/67.

### The census, re-measured

    the estate: 141 test files, 85 of them run by a registered spec,
                54 declared with a reason, 2 undeclared, 0 dangling

The 2 undeclared are `test_formal_read_before_store.py` and
`test_formal_receiver_spelling.py`, which arrived with a merged branch and are
`bugs/TEST_estate_check_red_on_two_form3_test_files.md` — another worker's
claim, and pre-existing on this branch's base.

The census also now counts **both spellings** of "test file", which is
`bugs/UNTESTED_estate_check_only_sees_test_prefixed_files.md` (closed and
deleted with the fix). Four files were outside the inventory entirely before
that, and one of them — `formal/x86_64_model_test.py`, the only check on
`lib/X86.lean` that EXECUTES a machine model instead of typechecking it — ran
by nothing. It is registered now (`formal-x86-machine-model`) and on its first
run found a real model bug: `udivmod` disagrees with the hardware, real 4,
model 7905747460161236410. Filed as
`bugs/CODEGEN_x86_model_udivmod_disagrees_with_hardware.md` with the emitted
bytes, which rule out the obvious explanation.

### §5's other items are unchanged

Registering the 50 is done and was not this pass's work; §3.1's cached-test
hole and §4.1's test-that-writes-to-the-tree were closed on 2026-10-01. §3.3's
*general* form — a check that a file which reports its verdict in its own
stdout cannot be relied on for one — is still not written as a mechanism.
`tools/memcap.py` and `tools/procrun.py` still have no test of their own, and
`procrun` is still invisible to the orphan walk because neither is a test file
under either spelling.

## Status, 2026-10-01

Two of the four §5 items are closed and the census has moved; the rest stands.

* **§4.1 — the unregistered test that WRITES to the tree — is fixed.**
  `test_py314_full.py` took a constant destination and wrote
  `bugs/<CATEGORY>_<path>.md`, so 300 seconds of it produced 25 new bug docs
  and a `grammar_snippet_gen.cpp` at the repo root. It now takes `--root` (and
  a missing tree is exit 2, not a zero-file pass that looks green), writes its
  reports to `--out` — a fresh temp directory by default, printed at the end —
  and only writes into `bugs/` when `--write-to-bugs` says so. The
  investigation is unchanged; only the destination moved.
* **§3.1 — the cached test that could not see its subject — is fixed** (the
  `checked_run.py` side landed earlier; the registry now says
  `extra=['test_examples_parse.py', 'formal/examples']`, so the 46th example is
  covered the day it is added).
* **The estate's numbers, re-measured on this tree:** 135 `test_*.py`, 83 run
  by a registered spec, **54 declared with a reason in
  `test_suite.py`'s `UNREGISTERED` and 0 undeclared** — so the "50 unregistered,
  21 red" of §1 has become 54 of which none is undeclared. The
  "21 exit non-zero" half is still a measurement, not a fact, and re-running
  54 files is an hour of scheduling somebody should choose rather than a
  side effect of a doc edit.
* **§5's other three items are unchanged**: the four tests dead at import
  (`mojo/ast_nodes.mojo`, `mojo/parser.mojo`) are in another claim's write
  set; the Tier-2 reds are behaviour work in the async/coroutine code; and the
  general "does this test still reference anything that exists" check is not
  statically decidable, for the reason §3.2 gives.

The one thing §2's Tier-1 table is now wrong about is a *number* rather than a
shape: `test_x86_64_containers.py` is no longer 59/60 x86-64 and 52/60 arm64.
On 2026-10-01 it measures **59/60 on x86-64**, one `with-statement` refusal,
and it is `x86-containers` in `x86` with a marker that states the count.

---

## 1. The shape, measured

*Historical: the counts below are the 2026-07-28 measurement this document was
written from, and the 2026-10-01 re-measurement is in the Status section above.*

| | count | how |
| `test_*.py` in the repo | **81** | `find . -name 'test_*.py'`, all at the repo root |
| named by a registered spec's `cmd` | **33** | parse of `suite.REGISTRY`; there is no glob and no discovery, so a file must be spelled out |
| **unregistered** | **50** | 62% of the estate |
| …of those, exit 0 | 29 | each run directly, 300 s cap |
| …**exit non-zero** | **21** | and nothing in the tree reports any of them |
| …of those, failing at IMPORT | **4** | `mojo/ast_nodes.mojo` and `mojo/parser.mojo` do not exist |
| …hitting the 300 s cap | 2 | `test_coro_scoreboard.py`, `test_py314_full.py` |
| registered specs with `cache=True` | 12 | all 12 name their own test file; verified, and now pinned |

Two numbers are worth separating, because they have different fixes. **50
unregistered** is a registration problem. **21 red** is not: registering a red
test turns a silent hole into a loud one, which is the point, but it does not
make the underlying behaviour work. `FORMAL.md` §11.4 asks for the 80/20 and
says a precise cost is a deliverable, so both are listed and neither is
conflated with the other.

## 2. The inventory, ordered by what a silent wrong answer would cost

The ordering is the deliverable. A silent wrong answer is ranked above a loud
one at equal severity, because a loud one is already reported.

### Tier 1 — a wrong answer that nothing in the gate could see

| # | what | why it costs this much |
|---|---|---|
| 1 | **`examples-parse` cannot see the 45 files it guards** | It exists because `19bc0dd` took 4 of `formal/examples/*.mojo` out of the parser and the only symptom was a coverage number 4 points low. It is `cache=True` with `extra=['fire_compiler.py', 'test_examples_parse.py']` — and none of the 45 example files is in the key. **Proven, not argued:** `open()` instrumented through `check_key` reads 48 repo files and **0** of them are under `formal/examples/`. A `SyntaxError` in any example cannot move the key, so a recorded PASS replays. The test created to make that loud is gated behind a cache that makes it quiet. §3.1 |
| 2 | **4 tests dead at import on renamed files** | `test_myinterpreter_simple.py`, `test_myinterpreter_validation.py` (`mojo/ast_nodes.mojo`), `test_phase2_parser.py`, `test_phase2_parser_simple.py` (`mojo/parser.mojo`). **Neither file exists.** This is the `coro` failure verbatim, from `CLAUDE.md`: the same class, four more files, and the `coro` one was found by accident. §3.2 |
| 3 | **`test_x86_64_containers.py` (59/60 x86-64, 52/60 arm64) and `test_x86_64_examples.py`** | The only files that EXECUTE x86-64 code and check what it computed. `test_x86_64_containers.py` is red today on `with-statement` (item 1 of `bugs/FORMAL_arm64_slice_concat_and_with_refusal.md`, with the arm64 slice and list-concat cases as items 2 and 3) `bugs/FORMAL_arm64_slice_concat_and_with_refusal.md`. The `x86` bucket runs `test_formal.py` and a model-coverage sweep; neither answers a question. A two-backend disagreement in a container operation is invisible until one of these runs: that is exactly how the dict-comprehension value bug and the two-backends'-one-program arm64 subscript refusal were found. |
| 4 | **`test_arm64_encoders.py` (221 checks) and `test_x86_64_decode.py`** | Differential: our encoders against `as -arch arm64`, and every x86-64 encoder round-tripped through the decoder. A wrong encoder is a silently wrong instruction and the gate has no other way to see one. |
| 5 | **`test_ownership_destruct.py`** | It decides which locals get destructors emitted, it is in `cas._COMPILER_SOURCES` so it changes generated C, and its only tests are fixtures nothing runs. A missed destructor is a leak — silent, and unbounded. |
| 6 | **5 closure-capture files** | `test_transitive_closure_capture.py`, `test_python_source_mut_capture.py`, `test_general_mutable_closure_capture.py`, `test_mutable_async_capture.py`, `test_closure_capture_comptime_func_params.py`. A capture that binds the wrong cell computes a plausible wrong number. `test_general_mutable_closure_capture.py` is by-reference, which is the same frame-address defect `FORMAL.md` assigns to [4] on the *other* backend. |
| 7 | **`test_refusal_taxonomy.py`** (agent [4]'s) | 20 families and zero "other" is a claim; this is what holds it there. A taxonomy that silently collapses to one bucket is the failure the taxonomy was built to end, and it would collapse without a word. |

### Tier 2 — a real behaviour gap, currently red and unreported

All measured by running the file. Counts are the file's own.

| file | failing | what |
|---|---|---|
| `test_gimple_async_runner.py` | **36** | compiled-path async/await codegen, step B. The largest block of unrun failures in the tree. |
| `test_coro_future_await.py` | 17 | A3 future/await |
| `test_async_void_return.py` | 3 | `device_context.mojo` async void return |
| `test_taskgroup.py` | 3 | `TaskGroup` as a compiled type — structured concurrency, so cancellation correctness |
| `test_async_with_lock_guard.py` | 2 | `with BlockingScopedLock` — a lock not taken is a silent wrong answer in a concurrent program |
| `test_nested_async_generic.py` | 2 | nested comptime-bracket-parametrised async |
| `test_coro_detached_async.py` | 2 | A3 detached async |
| `test_mutable_async_capture.py` | 2 | mutable capture in async |
| `test_transitive_closure_capture.py` | 2 | also tier 1 |
| `test_async_runtime_scaffold.py` | 1 | step A of compiled-path async/await |
| `test_x86_64_containers.py` | 1 | also tier 1 |
| `test_dispatch_phase_c.py` | — | `AssertionError: DispatchSolver should have been instantiated`, in 0.1 s. A broken test, not a behaviour gap. |

**`test_coro_future_await.py` is also the naming casualty.** Its siblings were
renamed from `test_mojo_*` to `test_fire_*` in the round that broke the `coro`
bucket by naming the old names. The bucket got fixed; this family never got
looked at.

### Tier 3 — dead for a reason that is not a behaviour gap

| file | why | what closing it takes |
|---|---|---|
| `test_myinterpreter_simple.py`, `test_myinterpreter_validation.py` | name `mojo/ast_nodes.mojo` | Either the test moves to what the interpreter actually loads, or it is deleted. The second is defensible: the interpreter has been `fire_compiler` since the rename, and a test of a module that no longer exists is not a slow test, it is a wrong claim. **`test_myinterpreter_validation.py` is the expensive one to delete** — it validates the interpreter's output against Python's own tokenizer, and that check is worth having *somewhere*. It is the strongest cheap parity check in the tree and nothing runs it. |
| `test_phase2_parser.py`, `test_phase2_parser_simple.py` | name a `parser` module that does not exist | Same decision, and the same argument: the parser is `fire_compiler.py` now. |
| `test_type_system.py`, `test_type_system_integration.py` | `No module named 'pytest'` | pytest is not a dependency of this repo. A test that needs a package the gate does not install is a test the gate cannot run. |
| `test_mixed_cpp_link.py` | `NameError: name 'mojo' is not defined` | Almost certainly a post-rename spelling in the test. Cheap to look at. |
| `test_py314_full.py` | points at `~/net/Python-3.14.6`, **outside the repository** | Takes the path as an argument and skips LOUDLY, or it stays unrun. A registered test that silently skips when a path is absent is a gate that measures nothing, which is worse than an unrun file. **And see below — it is also the one file in the estate that WRITES to `bugs/`.** |
| `test_coro_bugs.py` | exits 0 while its own output reads `CFAIL=1 COMPILE=1` | §3.3 |
| `test_coro_scoreboard.py` | >300 s; a file whose output IS the measurement | It has no assertion, so there is nothing to fail. Either something reads it or it is a report, not a test. |
| `test_comptime_parity.py` (agent [4]'s) | ~275 s | Pure scheduling. The `proofs` bucket has no `excl` jobs that would collide. |

### Tier 4 — registered, but the gate is not the only thing that runs them

Nothing to do. Listed so the tiers are not read as "these are all broken":
`test_ownership_check.py`, the five `test_dispatch_*.py` (phase A/B/C, promotions,
integration — a phase-B change can regress phase A with nothing to notice), the
`test_myinterpreter.py` / `test_generators.py` / `test_async_execution.py`
interpreter-side files, the four `test_mixed_cpp_*` / `test_import_*` /
`test_dual_cpp_elaboration.py` toolchain-plumbing files, and
`test_refactor_bugs.py`. Each is declared in `test_suite.py`'s `UNREGISTERED`
with its reason, so a 51st orphan is loud.

---

## 3. The three findings worth acting on

### 3.1 A cached test cannot see the files it is about

**Measured.** `examples-parse` is `cache=True`; its subject is the 45 files of
`formal/examples/`. Instrumenting `open()` through `checked_run.check_key` shows
the key reads 48 repo files — the compiler's own sources, `fire_runtime.{c,h}`,
and the test — and **none** under `formal/examples/`. A `SyntaxError` in any of
the 45 cannot move the key, so a recorded PASS replays.

The reason it is unfixable in place is the shape of `extra`: a hand-kept list of
45 paths, where the 46th file is added by someone with no reason to know the list
exists. **A directory could not be expressed either** — `--extra <dir>` hashed
the directory as one opaque name, so editing a file inside it, adding one and
removing one all left the key still.

**Fixed on this side** (`checked_run.py`): `--extra` now takes a directory and
hashs its whole recursive contents, by relative path in sorted order, so a
rename moves the key and a `__pycache__` does not. **`tools/suite.py` is
integrator-owned**, so the one-line registry change is an INTERFACE REQUEST
carrying a verified diff. The fix is written as `extra=['formal/examples']`
rather than as 45 paths precisely so it cannot rot the next time.

### 3.2 Nothing checks that a test file is still a test of anything

Four files die at import naming `mojo/ast_nodes.mojo` and `mojo/parser.mojo`,
neither of which exists. `CLAUDE.md` records the identical failure for the `coro`
bucket — 20 cases failing to compile after a rename, suite reporting 0/20 for
two rounds, nothing expected and nothing reported — and the fix was applied to
`coro` alone. Nothing generalised from it.

`test_suite.py` already has the right shape for this and it is a *different
check*: `test_selfhost_key_is_complete` walks `fire.py`'s import closure and
fails if anything reachable is unhashed. There is no equivalent for "the files a
test names". That one is not statically decidable in general — a test's inputs
are whatever it opens — so §4 pins the decidable half instead.

### 3.3 A test that exits 0 while its own output reports a failure

`test_coro_bugs.py` prints `CFAIL=1 COMPILE=1` and exits **0**. A test whose
result is a string it prints is not a test. This is the same shape as the
`FORMAL.md` §7 note about `test_formal_dylib.py`'s `lib/` grep staying green
through two rounds of vacuous theorems: the exit code is the only thing the gate
reads, and anything that puts its verdict anywhere else is invisible by
construction.

**The general form, and it is worth a check later:** a non-zero exit is the only
verdict `tools/suite.py` can see, so a test that reports through stdout, through
a scoreboard file, or through a return value that nothing reads is a test that
cannot fail. `tools/suite.py` has a `reject=` pattern for exactly this shape
(`mojo_unsupported_iter` prints and exits 0) and it is the right tool — it is
simply not applied to the files that need it.

---

## 4. What is pinned, and how it was shown to be able to fail

`FORMAL.md` §11.2's trap for this agent is *"writing tests that cannot fail"*,
and the precedent it cites is a grep that stayed green through two rounds of
vacuous theorems. So every check below was **mutation-tested**: the property was
broken in the source and the corresponding check was required to report FAIL.
All eleven were detected; the tree was restored after each and the restore
verified by content.

| check | in | broken by | detected |
|---|---|---|---|
| a cached PASS replays, a FAILURE re-runs | `test_suite.py` | inverting `stale` in `checked_run.py` | 3 checks |
| a changed `--extra` input re-runs | `test_suite.py` | freezing the input | 1 |
| a directory's contents move the key | `test_suite.py` | `if os.path.isdir: parts += [path]; return` | 5 |
| a file ADDED / REMOVED / RENAMED inside it moves the key | `test_suite.py` | dropping the relative name | 1 |
| `__pycache__` and a stray `.pyc` do not | `test_suite.py` | removing either filter, separately | 1, 2 |
| a file's NAME is in the key | `test_suite.py` | `parts += [b'']` | 1 |
| the `--extra` list is sorted | `test_suite.py` | removing the `sorted` | 1 |
| every `test_*.py` is registered, or declared with a reason | `test_suite.py` | dropping one entry from the 50 | 2 |
| no excuse outlives its file | `test_suite.py` | renaming a declared entry to a deleted file | 2 |
| no excuse outlives its registration | `test_suite.py` | renaming one to a registered file | 2 |
| an excuse is a reason, not a shrug | `test_suite.py` | reducing one to `'no'` | 1 |

**Two checks are deliberately not mutation-testable, and saying so is part of the
result.** The two anti-vacuity guards — that the orphan walk finds more than 20
files, and that more than 10 are registered — only fire when reality is broken,
so removing one changes nothing observable. They are the same category as
`expect=` anti-rot: a guard against a state, not against a line of code.

**The trap this file's own tests had to avoid, and did.** A recorded PASS
reproduces the recorded stdout *byte for byte*, so a probe that greps the output
for a marker the command printed concludes the command ran, on the run where it
provably did not. Both new tests observe "did it run" by a side effect outside
the captured streams — a counter file — and confirm the replay from the
announcement on stderr as well. `test_artifact_cache` had already found this and
says so in its own comment; the new tests inherit the method rather than
rediscovering it.

### 4.1 An unregistered test that WRITES to the tree

Found by accident, by running the inventory. `test_py314_full.py` compiles every
`.py` file under `~/net/Python-3.14.6` and, for each one that fails, **writes a
new `bugs/<CATEGORY>_<path>.md`**. Its own docstring says it dedups against
`bugs/` on disk — which means the second run of a failing file writes nothing,
so the *presence* of a doc becomes the record that it was ever investigated.

Measured: running it for 300 s produced **25 new files in `bugs/`** and one
`grammar_snippet_gen.cpp` at the repo root. All 25 were mine to delete and none
of them was anybody's work, but the failure mode is not about who ran it. It is
that **a test which writes into a shared tree is not a test**, it is a process,
and `tools/suite.py` runs jobs 12-way parallel from a common checkout. Two
concurrent runs racing on the same category file, or a run that is killed
half-way (this one was, at the 300 s cap) leaving a truncated bug doc that the
dedup then treats as complete, are both quiet.

**This is the one item in the inventory where "do not register it" is not
conservative advice but the finding.** The other Tier-3 files are unrun tests;
this one is a write. Its two defects are separable and both are fixable — take
the root as an argument, write to a temp directory and print a diff, or gate it
behind an explicit flag — but until one is, it must not go near the runner.

## 5. Not done, and why

- **Registering the 50.** `tools/suite.py` is integrator-owned. The list is
  ready to be applied in the order of §2, and the five Tier-2 files in it should
  go in with an `expect=` and a reason rather than not at all — a red test that
  is declared is a report, and the same file unregistered is silence. §11.3
  forbids adding an `expect=` to make something green; these are red already and
  would be marked to say *what is red*, which is the marker working as intended.
- **Fixing the 21 red files.** Tier 3 is mostly deletion decisions (is a test of
  a module that no longer exists still a test?) and Tier 2 is behaviour work
  that belongs to whoever owns the async and coroutine code. None of it is
  [5]'s to land, and guessing at it would be worse than the inventory.
- **A general "does this test still reference anything that exists" check.** Not
  statically decidable — see §3.2. The decidable half is pinned (§4); the rest
  needs either a declared input list per test, which is the hand-kept list this
  document argues against, or an import-hook-based trace, which is a bigger
  machine than it looks.
- **`tools/memcap.py` and `tools/procrun.py`.** In this agent's write set, and
  thin: `memcap` has one indirect case (`test_suite.py`'s `mem` driver asserts a
  breach is RESOURCE, not FAIL) and `procrun` — which owns both the RSS
  measurement and the kill, the two things `memcap` exists to get right — has no
  test at all. It is not in the inventory above because it is not a
  `test_*.py`, so the orphan check cannot see it, which is itself the shape of
  the problem. Worth the next pass.
