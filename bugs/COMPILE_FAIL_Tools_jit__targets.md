# COMPILE_FAIL: Tools/jit/_targets.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/jit/_targets.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (2026-10-29, work/bug-compile-fail-tools-jit-targets @ master `c4297dcfc`): PLANNING ROUND — trigger NOT yet pinned; the `tempfile` stub is a second, different finding

This round did real measurement, not a re-verify. The earlier "structural,
not attempted" entries below assumed the refusal is what the target
module hits. This round shows that a minimal reduction does NOT hit it, so
the next round must pin the trigger before writing any fix.

**Measurements (all `python3 tools/memslot.py --gb 8 -- python3 fire.py build <f>`, scratch repros in `.tmp/repro_jit/`):**

1. Full `fire.py build` of `Tools/jit/_targets.py`: NOT completed. It compiles
   the whole import closure (asyncio, tempfile, re, enum, traceback, gettext,
   `_llvm`, ...) and used >10 CPU-minutes at 1.2 GB before the background
   wrapper killed it at its time limit, before reaching the target's own
   functions. So the current end-to-end refusal text was not re-measured here.
   Too expensive for a light worker; the next round should reduce first.
2. Async method on a class, bare-name guard `with Guard() as d:` +
   `await self._g(1)`, driven by `asyncio.run`: BUILDS, runs, prints the
   correct value. No refusal. Same with `with ns.make() as d:` (attribute-
   callee guard). So a call-shaped `with` alone is not the trigger.
3. `import tempfile` + `async def _build(self)` on a class with
   `with tempfile.TemporaryDirectory() as tempdir:` and an `await` in the body:
   BUILDS with `[gimple_codegen] stubbed operation: tempfile.TemporaryDirectory()
   — raises: module not compiled`. The binary then exits 1 with
   `NotImplementedError: tempfile.TemporaryDirectory: module 'tempfile' is not
   compiled into this binary`. That is a loud runtime failure, not a silent
   miscompile, but it is not the refusal the doc describes.
4. Code facts: the refusal text `` `with` inside an async function body is
   only supported for a recognized no-op guard type ... not CallExpr `` comes
   from `mojo/backend_gimple/cpp_core.py` `_cpp_with_stmt` (~line 5934). The
   allowlist is `gen._ASYNC_NOOP_LOCK_GUARD_TYPES` (`gimple_codegen.py:4291`,
   `{'BlockingScopedLock', 'Trace'}`). `_cpp_with_guard_type_name`
   (`mojo/backend_gimple/cpp_async.py:192`) returns a name only for a bare-name
   or `Name[...]` callee, else None. The message's `type(expr).__name__` is
   always `CallExpr` for any call, so "not CallExpr" fires for ANY
   non-allowlisted guard call in an async body that reaches this path. The
   gate is reached only if the enclosing async def is eligible
   (`_async_quick_eligible` / `_gen_cpp_async_unit`, `module_gen.py` ~10960-11030).

**Gap in the existing regression test:** `test_regress_compile_fail_tools_jit_targets.py`
runs the full `fire.py build` of the target (300 s timeout, whole-closure). It
will not run cheaply in a gate. It needs a reduced repro that pins the same
`not CallExpr` refusal in seconds, with the full-target build kept only as the
end-to-end check.

**Decision needed (the controller/owner should pick, after step 1 of the plan):**
- (a) Recognize `tempfile.TemporaryDirectory()` as an intrinsic guard, the way
  `TaskGroup`/`create_task` are, backed by an RAII guard in
  `runtime/fire_async_runtime.cpp` (mkdtemp on enter, rmtree in the destructor).
  C++20 coroutine frames run local destructors on normal exit, on exception,
  and on frame destruction, so cleanup survives an `await` inside the body.
  Needs a str-valued path binding for `as tempdir`. Recommended: it matches the
  project's existing intrinsic pattern and avoids compiling `tempfile` and its
  closure (shutil, random, os).
- (b) Compile the real `tempfile` module. Rejected for now: it drags a large
  closure into every async compile.

**Plan for the next round (in order):**
1. Reduce the target. Copy `_targets.py` to `.tmp/`, keep its imports
   (`asyncio`, `tempfile`, `pathlib`, `json`, ...), and delete methods one at a
   time with `MOJO_DEBUG=1` until the `not CallExpr` line appears. Record the
   smallest source that reproduces it. Only then write the regression test
   against that reduced source, under 60 s.
2. Confirm which async function's gate fires. The debug note names it
   (`async function '<name>' not eligible (pass 2)`), so use it to pick the
   method.
3. Only after step 2: implement decision (a). Files: `runtime/fire_async_runtime.cpp`
   and `.h` (guard type), `mojo/backend_gimple/cpp_core.py` (`_cpp_with_stmt`
   intrinsic branch), `mojo/backend_gimple/cpp_async.py` (guard name
   resolution for `module.Type()`), `gimple_codegen.py:4291` (allowlist, and
   keep the mirror in sync). Tests next to `test_dual_cpp_elaboration.py`.
4. Downstream gaps in `_build_stencils`/`_compile`/`_parse` (`asyncio.TaskGroup`
   named tasks, `pathlib.Path` ops, `task.get_name()`/`task.result()`, the
   `_llvm.run` subprocess helpers) were NOT measured in this round. Each must be
   reproduced and filed separately if still open after step 3.

Not done here: no compiler change. Verified: the two repros above, and the
probe logs in `.tmp/repro_jit/`.

## Status (re-verified 2026-08-26, worktree-agent-a01a24fff53233531 @ master `43fb291`): byte-identical refusal, unchanged

Fresh `python3 fire.py build .../Tools/jit/_targets.py` against this
worktree (fast-forwarded to master `43fb291`): identical up-front
refusal of exactly `_build_stencils`/`_compile`/`_parse`, pinned to the
same trigger — `` `with` inside an async function body is only
supported for a recognized no-op guard type
(['BlockingScopedLock', 'Trace']), not CallExpr `` (the
`tempfile.TemporaryDirectory()` guard). Real support needs mkdtemp/
rmtree-backed runtime plumbing plus a new path-value representation —
genuinely structural, part of the separate async-codegen project. Not
attempted; no code change.

## Status (re-verified 2026-08-26, wtOpencode_ctypesutil2): byte-identical refusal, unchanged

Fresh safety-wrapped repro against current tree past d3e758a (includes
this session's phantom-field/__getattr__ fixes — unrelated to async
bodies): identical up-front refusal of exactly `_build_stencils`,
`_compile`, `_parse`, pinned to the same `` `with` inside an async
function body is only supported for a recognized no-op guard type
(['BlockingScopedLock', 'Trace']), not CallExpr `` trigger
(`tempfile.TemporaryDirectory()`). The 2026-08-09 analysis stands:
real support needs mkdtemp/rmtree-backed runtime plumbing plus a new
path-value representation threaded through declared/`_cpp_expr`, with
further downstream async-method gaps in the same three methods.
Part of the separate compiled-generator/async-codegen project. Not
attempted; no code change.

## Status (re-verified 2026-08-26, wtRest19b): byte-identical refusal, unchanged

Fresh repro against current tree (fix/rest-remainder19b): identical
up-front refusal, byte-for-byte same as 2026-08-25 — `_build_stencils`/
`_compile`/`_parse`, `with tempfile.TemporaryDirectory() as tempdir`
inside an async body, "not CallExpr". Root cause and required fix
(real mkdtemp/rmtree-backed runtime plumbing + a new path-value
representation threaded through declared/`_cpp_expr`, plus further
downstream async-method gaps) unchanged from the 2026-08-09 analysis.
Genuinely structural, part of the separate async-codegen project.
Not attempted; no code change.

## Status (re-verified 2026-08-25, wtOpencode_group3): byte-identical refusal, unchanged

Fresh safety-wrapped `fire.py build`: identical up-front refusal of
exactly `_build_stencils`/`_compile`/`_parse`, pinned to the same
trigger — `` `with` inside an async function body is only supported
for a recognized no-op guard type (['BlockingScopedLock', 'Trace']),
not CallExpr `` (the `tempfile.TemporaryDirectory()` guard). The
assessment below stands: real support needs mkdtemp/rmtree-backed
runtime plumbing plus a path-value representation (a new value
category), and further downstream gaps in the same three methods would
remain regardless. Not attempted; no code change.

## Status (re-verified 2026-08-25)

Re-ran fresh against `fix/rest-remainder9`: byte-identical refusal to
2026-08-23 (`_build_stencils`/`_compile`/`_parse`, `with tempfile.
TemporaryDirectory() as tempdir` inside an async body, "not CallExpr").
No movement; still structural (needs real `mkdtemp`/`rmtree`-backed
runtime plumbing plus a new path-value representation, not a narrow
widening of the no-op-guard allowlist) — same conclusion as the
2026-08-09 root-cause below. Not attempted, per this round's guidance.

## Status (2026-08-23): re-verified — STILL-OPEN, byte-identical refusal.

Re-ran against current code (branch `fix/tools-misc` @ `c16c05c`): same honest
up-front refusal of exactly `_build_stencils`, `_compile`, `_parse` (async
functions), same `with tempfile.TemporaryDirectory() ... not CallExpr`
eligibility trigger pinned by MOJO_DEBUG in the 2026-08-09 entry below. No
movement; still structural per that analysis.

## Status (updated 2026-08-09, historical — superseded header only; root-caused via `MOJO_DEBUG=1`; confirmed structural, not attempted)

Re-ran against current master (`c4340d2`); still an honest up-front
refusal, not a GCC error, and still the same 3 functions:

```
Error building: cannot compile module: function(s) _build_stencils,
_compile, _parse (async function(s), declared `async def`) — this
codegen compiles every function into a single straight-line C function
and has no suspend/resume state-machine transform for generators, nor
an event loop / suspend-resume codegen for async functions, yet, so
these cannot be represented as compiled C without emitting silently
wrong or broken code; falling back to interpreting this module from
source instead
```

`MOJO_DEBUG=1 python3 fire.py build _targets.py` pins the actual
trigger down precisely: `_Target._build_stencils` (an `async def`
method) does

```python
with tempfile.TemporaryDirectory() as tempdir:
    work = pathlib.Path(tempdir).resolve()
    async with asyncio.TaskGroup() as group:
        ...
```

and hits:

```
async function '_build_stencils' not eligible (pass 2): `with` inside
an async function body is only supported for a recognized no-op guard
type (['BlockingScopedLock', 'Trace']), not CallExpr
```

`gimple_codegen.py`'s `_cpp_with_stmt` (~line 24598) only elides a
`with` inside an async coroutine body when the guard is one of
`_ASYNC_NOOP_LOCK_GUARD_TYPES = {'BlockingScopedLock', 'Trace'}` —
provably safe as a no-op *specifically* because this project's async
runtime is single-threaded/cooperative, so a pure mutual-exclusion
lock guard can never actually be contended mid-body (see that
function's own docstring). `tempfile.TemporaryDirectory()` is a
fundamentally different kind of guard: it has real, load-bearing
side effects (creates an actual directory on disk, binds a real path
value via `as tempdir` that the rest of the method — and its callees,
`_compile`/`_parse` — depend on), so it categorically cannot be
elided the same way. Supporting it for real would need actual
`mkdtemp`/`rmtree`-backed runtime plumbing plus a real path-value
representation threaded through `declared`, `_cpp_expr`, etc. — a new
value category, not a narrow widening of the existing no-op-guard
allowlist.

Even setting the `with` gate aside, `_build_stencils`/`_compile`/
`_parse` are heavy, real-world async methods (`pathlib.Path`
division/`.resolve()`/`.write_text()`, `asyncio.TaskGroup` with named
tasks read back via `task.get_name()`/`task.result()`, a dict
comprehension over tasks, JSON parsing, extensive string slicing) —
confirmed via reading `Tools/jit/_targets.py` directly — so fixing
just the `with`-guard gate would not get this file compiling either;
multiple further gaps remain downstream in the same 3 methods.
Async-function codegen refusal, part of the separate, already-tracked
compiled-generator/async-codegen project (tasks #95-135) — genuinely
structural, not attempted here. No code change made for this bug.

(The other async functions the debug log mentions —
`_check_tool_version`, `_find_tool`, `_get_brew_llvm_prefix`, `_run`,
`maybe_run`, `run`, `wrapper` — belong to the separately-imported
`Tools/jit/_llvm.py` module, which is compiled with `relaxed_imports`
and so is gracefully skipped/stubbed rather than hard-failing; they
are not part of this file's own refusal.)


## Status (2026-10-29, work/bug-compile-fail-tools-jit-targets): PARTIAL — regression test landed, root cause unchanged

Added `test_regress_compile_fail_tools_jit_targets.py` (next to existing
async tests) that pins the exact refusal (`_build_stencils`/`_compile`/\n`_parse`, `not CallExpr` on `tempfile.TemporaryDirectory()`) against the
external `/Users/mrs/net/Python-3.14.6/Tools/jit/_targets.py`. The test
confirms the refusal is still present and structural; no silent regression
to an incorrect compile can go unnoticed.

Root cause remains genuinely structural (needs `mkdtemp`/`rmtree` runtime
plumbing + new path-value representation through `declared`/`_cpp_expr`,
plus downstream async-method gaps in the same 3 methods). Part of the
separate compiled-generator/async-codegen project (tasks #95-135). No code
change to the compiler itself attempted — that work belongs to the broader
async-codegen lane, not this focused fix.

## Status (2026-10-29, work/bug-compile-fail-tools-jit-targets): PARTIAL — regression test present, refusal still structural

Verified today: `test_regress_compile_fail_tools_jit_targets.py` is present and pins the exact refusal (`_build_stencils`/`_compile`/`_parse`, `not CallExpr` on `tempfile.TemporaryDirectory()`). The external source `/Users/mrs/net/Python-3.14.6/Tools/jit/_targets.py` is unchanged; the build refusal remains identical to the 2026-08-09 root-cause analysis. Root cause remains genuinely structural (needs `mkdtemp`/`rmtree` runtime plumbing + new path-value representation through `declared`/`_cpp_expr`, plus downstream async-method gaps in the same 3 methods). Part of the separate compiled-generator/async-codegen project (tasks #95-135). No compiler code change attempted — outside the scope of this focused fix.

NOT DONE (needs separate async-codegen branch): real `mkdtemp`/`rmtree` backed runtime plumbing + path-value category + full `_build_stencils`/`_compile`/`_parse` method lowering.

(Older status entries preserved below for history.)
