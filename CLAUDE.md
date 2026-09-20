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
- `mojo_compiler.py` is the single source of truth for all AST node definitions.
- `myinterpreter.py` imports AST nodes as `import mojo_compiler as N`.
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

## Quality gate for gimple/codegen-affecting changes
Before considering a change to `mojo_compiler.py` (the shared parser/AST),
`gimple_codegen.py`, or `module_loader.py` (or anything else on the compiled
path) done — including subagent work — run ALL of the following, not just
`test_gimple.py`/`test_module_cache.py`. This is the full gate; nothing here
is optional or "extra":

0. `make check-linkmode` (or `python3 test_link_mode.py`) — the real
   `driver.compile_program` link-mode pipeline `fire.py build` uses by
   default. Every OTHER step in this gate, PLUS `compile_stdlib.py`/
   `build_stdlib_dylib.py`, drives codegen through the single-translation-
   unit `do_imports=False` inline path instead — a bug specific to
   link-mode's own module/import registration is invisible to all of
   them (concretely: `bugs/COMPILE_FAIL_asyncio_futures.md`'s bare
   `from PKG import SUBMODULE` marker read as a value, and two further
   real link-mode bugs it surfaced — see the `bugs/CODEGEN_link_mode_
   *.md` docs — were all invisible to every other gate step and only
   found by adding this one). Added 2026-08-28 after those bugs
   surfaced.
1. `make check-selfhost` (fire.py compiling its own source). A parser AST
   change (e.g. a new node shape for some syntax) can be invisible to the
   interpreter-focused test suites yet silently break the compiled path,
   since gimple_codegen.py's lowering of that node shape is a separate,
   independently-maintained implementation from myinterpreter.py's evaluator.
   Concretely: a fix that changes `mojo_compiler.py`'s AST for `*`/`**`
   call-arguments (adding a `UnaryOp` wrapper) fixed the interpreter but
   broke `gimple_codegen.py`'s own self-compilation, because its
   `_lower_UnaryOp` had never seen that wrapper on those call sites before —
   `test_gimple.py`/`test_module_cache.py` both stayed green throughout.
2. A from-scratch stdlib dylib build (`rm -f build/libmojostdlib.dylib`
   then `python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib()"`,
   or just `python3 fire.py <any file>.mojo`) — check for `skip <module>:`
   lines in the output. The stdlib build is far larger and more varied than
   this repo's own source, and a type-resolution change can regress dozens
   of real stdlib modules from clean-compiling to falling back to source
   (a real regression, even though it's silently absorbed by the documented
   "skip and fall back" stopgap and won't show up as a hard failure anywhere
   else). Compare the skip count before/after your change — it should not
   increase. If it does, bisect which specific type/symbol triggered it
   before considering the change finished.
3. `python3 compile_stdlib.py` — a WIDER check than step 2: it also attempts
   `test/`, `tools/`, `benchmarks/` etc. under the stdlib tree (664 files as
   of this writing), each via a real `gcc -fsyntax-only` check on the
   generated GIMPLE, not just the 291 modules step 2's dylib link needs.
   Compare `FAILED: N (E expected, U unexpected)` before/after — `U`
   (unexpected) must not increase. A file that's a genuine, currently-out-
   of-reach gap (not a regression) belongs in `EXPECTED_FAILURES` at the top
   of `compile_stdlib.py` with a comment explaining why, not silently
   ignored — an unexplained "unexpected" failure is exactly what this gate
   step exists to catch.
4. `make bootstrap` (3-stage self-compilation byte-identity check) if the
   change touches `mojo_compiler.py`, `gimple_codegen.py`, `module_loader.py`,
   or any `gimple_*.py` — the fullest-coverage check available; `make
   check-selfhost` alone is a faster subset, not a substitute. `stage2`/
   `stage3` exercise the self-hosted binary's own native codegen for every
   file they dump (the C runtime's python3-subprocess fallback was removed
   2026-09-19 — see step 5's note — so there is no other path left for
   them to take; this makes `stage2`/`stage3` meaningfully STRONGER than
   before that removal, since they previously silently delegated the real
   codegen work to the same subprocess and only verified argument-parsing/
   orchestration determinism).
5. `make check-native-dumpfull` (or `python3 test_native_dumpfull.py`) —
   diffs `./mojoc fire.py --dump-full`'s actual output BYTE-FOR-BYTE
   against the python3-interpreted reference's own `--dump-full`, not just
   exit code. Steps 0-3 all drive codegen through the python3-interpreted
   reference implementation; this one exercises the self-hosted `mojoc`
   BINARY's own compiled (native) codegen running on real work. A
   native-codegen-only bug can produce a wrong-but-exit-0 artifact every
   other step is structurally blind to — this happened for real
   2026-08-13→09-13: a fix that silenced a known SIGBUS in that path
   turned out to silently drop two compiled sibling modules instead
   (1.4M-line diff from correct), and every other check-* target stayed
   green throughout, including `make check-selfhost` and `make bootstrap`.
   Added 2026-09-13 (see the `design-container-typing-audit`/
   `selfhost-dump-full-module-drop` project memories) specifically because
   steps 0-3 all missed that regression. (Renamed 2026-09-19 from
   `check-noshim-dumpfull`/`test_noshim_dumpfull.py` when the C runtime's
   python3-subprocess fallback was removed entirely — see
   `gimple_codegen_compile_to_gimple`'s own comment in runtime/
   fire_runtime.c — so there is no more "shim vs no-shim" distinction,
   only "python-interpreted reference vs self-hosted native".)

**Status as of 2026-09-20**: removing the subprocess fallback (so `stage2`/
`stage3` and native `--dump-full` genuinely exercise the self-hosted
binary's own codegen for the first time) surfaced a real, substantial
backlog of self-hosted-only bugs, most now fixed — see
`bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md` for the full
history. `make bootstrap`'s stage1-vs-stage2 `.ci` divergence count went
14 → 0 for individual per-file dumps; the ROOT CAUSES found (all in code
this compiler self-hosts, not user-facing bugs) were a recurring pattern:
an untyped function parameter/return value whose element type (str vs
int64_t, for a `list`/`set`/`dict`) can't be tracked across a function-call
boundary the way a locally-scoped literal's element type can — see
`ownership_destruct.py`'s own extensive docstrings (`_as_str`,
`_intersect_all`, `begin_function`) for the full mechanism and its
limits. `make bootstrap`'s own internal whole-program `--dump-full
fire.py` self-check (inside the `stage2`/`stage3` targets) still crashes
intermittently on real, large, multi-module input (confirmed via lldb:
`ownership_destruct._dfa_stmt`'s `assigned.update(...)` call, on a
`TryStmt`/ambiguous-import-fallback code shape not yet isolated to a
minimal repro) — this is the one known remaining gap, not yet root-
caused to a specific fix the way every other divergence in this backlog
was. Do not assume `make bootstrap`/`make check-native-dumpfull` are
fully green without re-checking this doc's latest status entry.

A change passing `test_gimple.py`/`test_module_cache.py`/`make check-selfhost`
alone is NOT sufficient evidence the compiled path is unaffected — only
`compile_stdlib.py` and the stdlib dylib build actually exercise the huge
breadth of real Mojo source this compiler needs to keep working, and only
`make bootstrap`/`make check-native-dumpfull` verify the self-hosted
BINARY's own native codegen (not just the python3-interpreted reference's)
produces correct output, not just a clean exit code.
