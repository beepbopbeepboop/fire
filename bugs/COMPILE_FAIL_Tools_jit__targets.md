# COMPILE_FAIL: Tools/jit/_targets.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/jit/_targets.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

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

Fresh safety-wrapped `mojo.py build`: identical up-front refusal of
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

`MOJO_DEBUG=1 python3 mojo.py build _targets.py` pins the actual
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


(An older status further down used to show a stale raw GCC warning dump and a now-unreproducible `_stencils.py` enum-keyword parse error from a much earlier run — removed as no longer reflecting current behavior; re-verified 2026-08-09 that the module now fails cleanly at the up-front async-refusal gate above, with no `_stencils` import error at all.)
