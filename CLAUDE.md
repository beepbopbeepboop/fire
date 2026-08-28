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

## Quality gate for gimple/codegen-affecting changes
Before considering a change to `mojo_compiler.py` (the shared parser/AST),
`gimple_codegen.py`, or `module_loader.py` (or anything else on the compiled
path) done — including subagent work — run ALL of the following, not just
`test_gimple.py`/`test_module_cache.py`. This is the full gate; nothing here
is optional or "extra":

0. `make check-linkmode` (or `python3 test_link_mode.py`) — the real
   `driver.compile_program` link-mode pipeline `mojo.py build` uses by
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
1. `make check-selfhost` (mojo.py compiling its own source). A parser AST
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
   or just `python3 mojo.py <any file>.mojo`) — check for `skip <module>:`
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
   check-selfhost` alone is a faster subset, not a substitute.

A change passing `test_gimple.py`/`test_module_cache.py`/`make check-selfhost`
alone is NOT sufficient evidence the compiled path is unaffected — only
`compile_stdlib.py` and the stdlib dylib build actually exercise the huge
breadth of real Mojo source this compiler needs to keep working, and only
`make bootstrap` verifies the compiler's own self-hosted output is stable
under repeated self-compilation.
