# Stdlib Transpilation Status

This document describes the current state of compiling the upstream Mojo
standard library through the compiler. It covers what is tested, what works,
and the gaps that remain. (Earlier session-by-session history has been
retired; consult git history if you need it. See `PLAN.md` for open bugs and
`IMPL.md` for implemented-feature history.)

## What is tested

`compile_stdlib.py` runs every `.mojo` file in the upstream stdlib tree
through the **real GIMPLE backend** (`compile_module_to_c`, from
`build_stdlib_dylib.py`, which calls `gimple_codegen.py` — the same codegen
path used by the self-hosting bootstrap, `make check-gimple`, and the stdlib
dylib build) and reports pass/fail per file. A file **passes** when codegen
succeeds and the emitted C passes `gcc -fgimple -fsyntax-only` (or is
legitimately empty, e.g. a license-only `__init__.mojo`).

> Scope: this exercises parsing, AST rewriting, and the full GIMPLE lowering
> — a real, non-trivial guarantee — but it is still a **syntax-only** check
> (`-fsyntax-only`, no link, no run). It does not assert that the emitted
> code produces correct behavior at runtime, nor does it link or execute
> anything. This is a single unified pipeline with the self-hosting
> bootstrap and `make check-gimple` (same `gimple_codegen.py`), just a much
> larger, real-world input corpus than `test_gimple.py`'s hand-written
> snippet suite.

The stdlib root is located via `module_loader.STDLIB_PATH` (override with the
`MOJO_STDLIB` environment variable, though it's optional — the path is
hardcoded as a fallback). Roots are scanned in this order:

```bash
python3 compile_stdlib.py                        # all default roots (see below)
python3 compile_stdlib.py --roots test           # one or more named roots
python3 compile_stdlib.py --roots std/_core,std/collections,std/io,std/math,std/os
                                                  # narrower slice (used by CLAUDE.md's quality gate)
python3 compile_stdlib.py --module time          # a single module under std/
```

`DEFAULT_ROOTS` is `[benchmarks, std, test, tools, _core, collections, io,
math, os]` — the last five are legacy entries from before the stdlib was
restructured under `std/`; they match nothing at the tree root today and
contribute zero files. Effective default coverage is just `benchmarks` +
`std` + `test` + `tools`. Supports `-j N` parallel workers (default: all
cores) via `--roots`/no-flag runs; use `-j1` if you need deterministic
single-process output (e.g. while instrumenting the codegen with a
monkeypatch for debugging).

## Current results (2026-07-06)

| Root | Passing | Notes |
|---|---|---|
| `benchmarks` | 21 / 21 | real client code exercising the library |
| `std` | 282 / 282 | the library proper |
| `test` | 343 / 343 | the upstream test corpus |
| `tools` | 1 / 1 | |
| **Total** | **647 / 647** | zero known failures |

No currently-known failing file. (An earlier version of this document
tracked a single failure, `test/format/test_tstring.mojo` — nested template
strings with alternating quote characters, which broke the old regex-based
single-pass string scanner. That file now transpiles and passes the GIMPLE
syntax check cleanly; re-verified directly via `compile_module_to_c` as part
of writing this update, not just inferred from the aggregate count.)

Companion suites (run via `make check`):

| Suite | Command | Result |
|---|---|---|
| GIMPLE backend unit tests | `make check-gimple` | 159 / 159 |
| Execution tests | `make check-runner` | 17 / 17 |
| Module-cache tests | `make check-modcache` | 53 / 53 |
| Self-host compile guard | `make check-selfhost` | fire.py compiles itself to a linked binary |

`make check` = all four of the above (`check-gimple`, `check-runner`,
`check-modcache`, `check-selfhost`). The self-hosting **bootstrap**
(`make bootstrap`: stage1-3 + `verify` + `validate-all`) is a separate
target, not gated into `check`.

## Gaps and caveats

- **Syntax-only guarantee.** Passing means "parses, rewrites, lowers to
  GIMPLE C, and passes `gcc -fgimple -fsyntax-only`" — a real backend
  guarantee, but not "links, runs, and produces correct output." Many
  advanced constructs are parsed and then intentionally simplified or
  stubbed in the emitted output (generics are monomorphized or erased, MLIR
  forms are lowered via a table with deliberate gaps, keyword-only subscript
  params are consumed-and-discarded, etc.). See `IMPL.md` for the
  per-feature behavior, and `PLAN.md` for known runtime-behavior gaps (e.g.
  `re` module flags, typed exception dispatch).
- **`make bootstrap` is a separate, stronger check.** It self-hosts the
  compiler (`fire.py` compiling itself, linking, and running the result),
  which exercises real end-to-end execution rather than syntax-checking —
  and, as of 2026-07-06, passes cleanly (stage1/stage2/stage3/`verify`; see
  `IMPL.md`'s "Recent Work (2026-07)"). `validate-all` still fails a
  file-count check for unrelated, pre-existing reasons (see `PLAN.md`).
- **Deep semantics not modeled.** Full parameterized-type elaboration, trait
  resolution, ownership/lifetime semantics, and some MLIR lowering forms are
  not implemented; the front end parses these forms and the backend
  approximates or stubs them (see `IMPL.md`'s MLIR-floor section for what's
  actually lowered vs. deferred-with-reason).

## Reproducing

```bash
python3 compile_stdlib.py                  # full sweep, prints "PASSED: N" / "FAILED: N"
python3 compile_stdlib.py --roots test     # narrow to the test corpus
python3 compile_stdlib.py --module format  # narrow to one std/ module
make check-gimple                          # 159 backend unit tests
make check-runner                          # 17 execution tests
```

To debug a single file's failure, feed it directly to the same codegen path
`compile_stdlib.py` uses:

```bash
python3 -c "
from build_stdlib_dylib import compile_module_to_c
src = open('path/to/file.mojo').read()
print(compile_module_to_c(src, 'path/to/file.mojo', 'debug_name'))
"
```

`python3 mojo_compiler.py < path/to/file.mojo` (the compiler's own lexer/
parser CLI, emitting a rewritten-Python form rather than GIMPLE C) is a
lighter first check for pure parse failures, but a file can pass that and
still fail in the real GIMPLE lowering (`compile_module_to_c`) — it is a
different, narrower code path than what `compile_stdlib.py` actually
exercises, so a failure specific to codegen (as opposed to parsing) won't
reproduce there.

Note that the tokenizer pools multi-line strings into placeholders before
lexing, which collapses physical line numbers — reported error lines for
files with large docstrings are unreliable; locate failures by the token
context instead.
