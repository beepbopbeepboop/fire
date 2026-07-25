# CODEGEN: two top-level `def NAME(...):` under mutually-exclusive `if`/`else` branches collide

## Repro

```python
import sys
if sys.platform == 'win32':
    def wait(x):
        return x + 1
else:
    def wait(x):
        return x + 2

def f():
    print(wait(5))
f()
```

- `python3 mojo.py run repro.py` (interpreter): correct — prints `7` (the
  `else` branch's definition, since that's the one actually executed on
  this platform).
- `python3 mojo.py build repro.py -o out`: fails to compile:
  ```
  repro.py:11:9: error: conflicting types for 'wait'; have 'int64_t()' {aka 'long long int()'}
  ```

Real stdlib trigger: `Lib/multiprocessing/connection.py` defines
`def wait(object_list, timeout=None):` twice at module level — once inside
an `if sys.platform == 'win32':` block (~line 1086) and once inside the
matching `else:` (~line 1176), each providing a platform-specific
implementation of the same public module function. This is a common,
legitimate Python idiom for platform-conditional top-level function
definitions (`bugs/COMPILE_FAIL_multiprocessing_connection.md`).

## Root cause

Real Python resolves this naturally at runtime: whichever `if`/`else`
branch actually executes is the only one that runs its `def` statement,
rebinding the module-level name `wait` to that one function object — the
other branch's `def` never executes, so there's only ever one `wait` in
scope at a time.

This compiler's codegen path appears to compile EVERY top-level `def`
statement it finds into a distinct top-level C function, regardless of
which conditional branch (`if`/`elif`/`else`) it's textually nested inside
— so both `def wait(x):` bodies get lowered into C functions that both want
the same top-level (unmangled, since it's a module-level function, not a
method) C symbol name `wait`, causing a redefinition/conflicting-types
error at the C level. The interpreter path is unaffected because it
naturally only ever registers whichever branch's `def` statement actually
executes, matching real Python semantics.

## Suggested fix

Not yet planned — needs investigation into how `gimple_codegen.py` currently
discovers/enumerates top-level function definitions to compile (does it
walk the whole module body unconditionally regardless of surrounding
`if`/`else` nesting, or does it already have some notion of "which branch
is live"?). Given real code commonly uses this exact idiom for
platform-specific implementations of the same function name, a reasonable
fix direction: when compiling top-level functions, either (a) mangle
functions found inside conditional branches distinctly per-branch and have
call sites dispatch based on the same condition (matching real semantics
exactly, but potentially complex), or (b) since this codegen already
falls back to interpreting modules it can't fully compile (the documented
"skip module, fall back to source" mechanism referenced in CLAUDE.md), a
simpler and likely acceptable interim stance might be picking a single
"winning" definition using some fixed, deterministic rule (e.g. last one
wins, matching sequential top-to-bottom module execution when only one
branch is taken) — investigate which of these directions best fits how
this codegen already handles similar control-flow-dependent top-level
constructs elsewhere, and use judgment on scope vs. correctness per
CLAUDE.md ("never pick the simple/quick fix... pick the production-quality
approach") balanced against not over-engineering a narrow real-world case.

## Status
**Fixed** (as an honest, deliberate refusal — not a full runtime-dispatch
implementation; see "Why not option A" below).

### What was actually going on
Investigation showed the root cause was worse than the original repro's gcc
error suggested. `gen_module`'s pre-passes (the module-level closure scan a
few hundred lines down, and the loop that calls `gen_func` on each top-level
`FunctionDef`) only ever walk *direct* top-level statements in `stmts` — they
never look inside `IfStmt.then_body`/`elifs`/`else_body`. So a `def` nested
in a module-scope `if`/`else` is not recognized as a top-level function at
all: it falls through to `_gen_stmt_FunctionDef`'s closure path, which finds
no pre-pass `ClosureInfo` for it and just emits `/* TODO: closure 'NAME' (no
pre-pass info) */` — i.e. it is **never compiled**, silently. The call site
then has nothing to resolve `wait` against and falls back to emitting a bare
`int64_t wait (...);` extern declaration, which is what collided — not with
the *other* branch's `wait`, but with **libc's own `pid_t wait(int *)`** from
`<sys/wait.h>` (confirmed by re-running the exact repro and reading gcc's
"previous declaration" note). A single (non-duplicated) conditional
top-level `def` is equally broken today — confirmed with a second repro
(`greet` defined only under `if sys.platform == 'darwin':`, no `else`) which
fails at link time with "Undefined symbols ... _greet", not a compile error.

### Chosen fix: Option B (honest refusal + existing fallback), not A or C
- **Option A** (mangle each branch's def distinctly + make call sites
  runtime-dispatch on the same condition) would be the most semantically
  faithful, but is a substantial feature (new call-site codegen, condition
  re-evaluation, mangling scheme) for what the rest of this pass doesn't
  even support today for the *single*-definition case either. Building it
  just for this ticket would be scope creep.
- **Option C** ("last one wins" / pick a platform branch) was rejected as
  explicitly unsafe per the ticket's own caution: this compiler doesn't
  track a specific target platform for `sys.platform`-style conditions, so
  guessing wrong would silently produce the *other* platform's behavior —
  strictly worse than refusing to compile.
- **Option B** was chosen: `gen_module` now detects — via an iterative
  worklist over module-level `IfStmt`/`elifs`/`else_body` chains (not a
  self-recursive nested function; see gotcha below) — any top-level function
  name defined more than once across sibling conditional branches, and
  raises `RuntimeError` immediately with a clear diagnostic. Every existing
  caller of `gen_module` already treats a codegen exception as "this
  module/file can't be compiled natively": `_compile_imported_module` catches
  it and rolls back, letting the module fall back to dylib/extern/interpreted
  resolution (the documented "skip module" stopgap); `build_stdlib_dylib.py`'s
  per-module job and `compile_stdlib.py` likewise catch-and-skip; and
  `mojo.py build_executable` catches it and prints a clear
  "Error building: ..." message instead of the previous confusing gcc
  symbol-clash output. This does not silently pick a possibly-wrong branch
  and does not require new runtime-dispatch machinery.
- This fix intentionally does **not** make the single-definition
  conditional-`def` case (e.g. `greet` above) actually compile — that is a
  separate, pre-existing, broader gap (conditional top-level defs are simply
  unsupported by this codegen's top-level-function discovery) that was
  uncovered during investigation but is out of scope for this ticket, which
  is specifically about the name-collision shape. It remains an honest
  failure (a link error) exactly as before, not a new regression.

### Changes
- `gimple_codegen.py`, `gen_module` (~line 14335 area, right after the
  existing "Overloaded top-level functions ... can't be emitted as distinct
  C symbols" filter): added detection of same-named top-level `def`s nested
  in sibling `if`/`elif`/`else` branches, raising `RuntimeError` when found.
  Implemented as an explicit iterative worklist rather than a recursive
  nested helper function — a first version used a self-recursive nested
  `def _collect_conditional_toplevel_defs(...)`, which broke
  `make check-selfhost` with an undefined symbol
  (`__collect_conditional_toplevel_defs`): a nested function calling itself
  does not survive this compiler's own self-host closure-lifting (the same
  documented gotcha as `_register_imported_structs`'s `_collect` helper
  elsewhere in this file).
- `test_gimple.py`: added a `test_raises(name, mojo_src, expected_substr)`
  helper (compile_to_gimple must raise with a message containing
  `expected_substr`, rather than crash gcc on broken C or silently emit wrong
  code) and a regression test `conditional_toplevel_def_name_collision` using
  the ticket's minimal repro.

### Quality gate results
- `python3 test_gimple.py`: 180 passed, 0 failed (179 pre-existing + 1 new).
- `python3 test_module_cache.py`: 64 passed, 0 failed.
- `make check-selfhost`: passes (`mojo.py` compiling its own source, clean
  build + link).
- From-scratch stdlib dylib build (`rm -f build/libmojostdlib.dylib` +
  `build_stdlib_dylib.build_stdlib(use_cache=False, jobs=8)`): stderr output
  byte-for-byte identical before and after the fix (153 lines of pre-existing
  "drop stale export" reflection-cleanup notices; 0 "skip"/"exclude" lines in
  both). No skip-count regression; stdlib build was already at 0 skips
  (matching the memory note "570/25→595/0, every stdlib file compiles").

### Manual verification
- `python3 mojo.py run /tmp/repro.py` → `7` (interpreter, unaffected,
  correctly picks the `else` branch).
- `python3 mojo.py build /tmp/repro.py -o /tmp/repro_out` → now fails
  cleanly with `Error building: cannot compile module: top-level function(s)
  wait are each defined more than once across mutually-exclusive if/elif/else
  branches...` instead of the old confusing `conflicting types for 'wait'`
  gcc/libc symbol-clash output.
- `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py
  -o /tmp/mc_out` → fails the same clean way, listing all four real
  colliding names in that file (`Pipe`, `rebuild_connection`,
  `reduce_connection`, `wait`) — an honest, immediate refusal rather than the
  old confusing partial-compile-then-gcc-error output (that file also has
  other, unrelated pre-existing compile issues tracked separately in
  `bugs/COMPILE_FAIL_multiprocessing_connection.md`, e.g. `invalid operands
  to binary %`; those are not addressed here and are no longer even reached
  since this new check now fails fast).
