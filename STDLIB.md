# Stdlib Transpilation Status

This document describes the current state of compiling the upstream Mojo
standard library through our front end. It covers what is tested, what works,
what fails, and the gaps that remain. (Earlier session-by-session history has
been retired; consult git history if you need it.)

## What is tested

`compile_stdlib.py` runs every `.mojo` file in the upstream stdlib tree through
`mojo_compiler.py` (the lexer/parser/transpiler) and reports pass/fail per file.
A file **passes** when the compiler exits 0 and produces non-empty output (or is
legitimately empty, e.g. a license-only `__init__.mojo`).

> Scope: this is a **front-end / transpile** check — it verifies that each file
> *parses and lowers* without error. It does **not** assert semantic correctness
> of the emitted output, and it is a separate pipeline from the GIMPLE backend
> (`gimple_codegen.py`) exercised by `make check-gimple`.

The stdlib root is located via `module_loader.STDLIB_PATH` (override with the
`MOJO_STDLIB` environment variable). Four subtrees are scanned, in this order:

```bash
python3 compile_stdlib.py                  # all roots: benchmarks, std, test, tools
python3 compile_stdlib.py --roots test     # one or more named roots
python3 compile_stdlib.py --module time    # a single module under std/
```

## Current results

| Root | Passing | Notes |
|---|---|---|
| `benchmarks` | 21 / 21 | real client code exercising the library |
| `std` | 291 / 291 | the library proper |
| `test` | 329 / 330 | the upstream test corpus |
| `tools` | 1 / 1 | |
| **Total** | **642 / 643** | |

Companion suites (run via `make check`):

| Suite | Command | Result |
|---|---|---|
| GIMPLE backend unit tests | `make check-gimple` | 142 / 142 |
| Execution tests | `make check-runner` | 8 / 8 |

## What does not work

### Nested template strings (1 file)

`test/format/test_tstring.mojo` is the only failing file. It uses t-strings
nested inside their own interpolations, alternating quote characters:

```mojo
String(t"L1: {t'L2: {t"L3: {val}"}'}")
```

Single-level t-strings (`t"Hello, {name}!"`, `t"{x + y}"`, escaped braces
`t"{{...}}"`) all work — they are lexed as one `STRING` token. Nested t-strings
do not, because the string scanner is regex-based and terminates at the first
matching quote, so the inner `"` closes the outer string and the remaining
`: {val}` is mis-lexed as code (`Unexpected COLON`).

A real fix requires a recursive, interpolation-aware string lexer (track brace
depth inside an interpolation and re-enter string scanning for nested literals)
rather than the current single-pass regex. This is a meaningfully larger change
than the other front-end features and is deliberately deferred.

## Gaps and caveats

- **Transpile-only guarantee.** Passing means "parsed and lowered," not
  "produces correct/runnable output." Many advanced constructs are parsed and
  then intentionally simplified or stubbed in the emitted output (generics are
  stripped, MLIR forms are skipped/annotated, keyword-only subscript params are
  consumed-and-discarded, etc.). See `IMPL.md` for the per-feature behavior.
- **Two separate pipelines.** `compile_stdlib.py` exercises `mojo_compiler.py`.
  The self-hosting bootstrap and `make check-gimple` exercise `gimple_codegen.py`
  (via `mojo.py`). A file transpiling here does not imply it compiles through the
  GIMPLE backend.
- **Bootstrap stage 2 segfault.** `make check` also runs the three bootstrap
  stages; the self-hosted `mojo` binary currently segfaults at stage 2. This is
  a known, pre-existing **codegen** bug in the GIMPLE backend, independent of the
  front-end work tracked here.
- **Deep semantics not modeled.** Full parameterized-type elaboration, trait
  resolution, ownership/lifetime semantics, and MLIR lowering are not
  implemented in the transpiler; the front end parses these forms and the
  backend approximates or stubs them.

## Reproducing

```bash
python3 compile_stdlib.py                  # full sweep, prints "Results: N passed, M failed"
python3 compile_stdlib.py --roots test     # narrow to the test corpus
make check-gimple                          # 142 backend unit tests
make check-runner                          # 8 execution tests
```

To debug a single file's parse failure, feed it to the compiler directly:

```bash
python3 mojo_compiler.py < path/to/file.mojo
```

Note that the tokenizer pools multi-line strings into placeholders before
lexing, which collapses physical line numbers — reported error lines for files
with large docstrings are unreliable; locate failures by the token context
instead.
