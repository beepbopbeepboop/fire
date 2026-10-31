# COMPILE_FAIL: Tools/jit/_targets.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/jit/_targets.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (2026-10-29, work/bug-compile-fail-tools-jit-targets, round 2): the refusal is cpp-only; the shipped default backend ACCEPTS the reduced shape

Measured this round (`python3 tools/memslot.py --gb 8 -- ...`, repro in
`.tmp/jit/repro.mojo`, the same source as the reduced repro below):

1. **Default backend (`MOJO_CORO` unset = `stackswitch`, `mojo/middle/coro.py`
   §5.5 cutover): `python3 fire.py build repro.mojo` SUCCEEDS**, exit 0,
   peak 0.1 GB, ~2 min wall. `./repro` prints `ok`. `main()` never calls
   `build()`, so the runtime stub was not exercised by this run. The earlier
   planning round's observation (`tempfile.TemporaryDirectory()` emitted as
   `/* ... raises: module not compiled */` with `tempdir` bound to it) is
   consistent with this, but was not re-run here.
2. **`MOJO_CORO=cpp`: the refusal reproduces** (`test_regress_compile_fail_tools_jit_guard.py`
   passes: `refused, names 'build': True`, exit 0).

So the `not CallExpr` COMPILE_FAIL in this doc is an escape-hatch (cpp)
refusal. It is NOT what the shipped backend does with the reduced shape.

**Consequence for the existing test:** `test_regress_compile_fail_tools_jit_targets.py`
runs `fire.py build` on the full `_targets.py` with the DEFAULT backend and
asserts `not CallExpr` in its output. On the default backend that string is
produced only if something else in the target still refuses. NOT measured
(whole-closure, >10 CPU-min for a light worker). Treat that test as unverified
on the default path until someone runs it on the integrator.

**Decision needed (owner), before any code change:** the defect that matters
for the shipped backend is that `with tempfile.TemporaryDirectory() as d:` in an
`async def` compiles silently to a runtime stub, with `d` bound to that stub.
Options:
- (i) Make the stackswitch backend refuse a non-lock `with` in an async body,
  the way cpp does. Cheap, honest, turns a silent stub into a COMPILE_FAIL. Risk:
  `coro.py`'s `_lock_withs_ok` / eligibility is shared with plain `with open(...)`
  in async bodies across the stdlib, so this moves the `stdlib-syntax` /
  `stdlib-dylib` `U`/`skip` counts. Needs the integrator's gate to judge.
- (ii) Implement the intrinsic RAII guard (the recommended decision (a) below),
  in BOTH backends. Real feature; larger.
- Either way the cpp refusal stays as is.

**Next steps once the owner picks:** for (i), in `mojo/middle/coro.py`
eligibility, add a refusal for any `WithStmt` in an async body whose guard is
not in the allowlist, mirrored in `cpp_core.py`'s `_cpp_with_stmt` (already
refuses), then pin with a test under the default backend (fire.py build of the
reduced repro must exit non-zero and name `build`). Verify the `stdlib-syntax`
`U` count does not increase.

## Status (2026-10-29, superseded by the entry below): PLANNING ROUND — trigger NOT yet pinned at the time

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


## Status (2026-10-29, work/bug-compile-fail-tools-jit-targets): TRIGGER PINNED, reduced repro in seconds; the tempfile allowlist entry was dead code and is reverted

Correction to the earlier PARTIAL entry: adding `tempfile` to
`_ASYNC_NOOP_LOCK_GUARD_TYPES` (commit dc03880) changed nothing and could not
have. `_cpp_with_guard_type_name` (`mojo/backend_gimple/cpp_async.py:192`) only
resolves an `IdentExpr` or `SubscriptExpr` callee; `tempfile.TemporaryDirectory()`
is a `MemberExpr`, so the name is `None` and never matches the allowlist. The
refusal was still raised. The entry is removed, and `test_regress_compile_fail_tools_jit_guard.py`
(renamed from `..._fixed.py`) now pins the refusal instead of asserting a fix.
It would also have been unsound: the guard creates a real directory and binds a
real path to `as tempdir`, so it is not a no-op like a lock or a trace span.

**Reduced repro (seconds, in-process, `python3 tools/memslot.py --gb 8 -- ...`):**

    MOJO_CORO=cpp MOJO_DEBUG=1 python3 -c "<source below>"

```
import asyncio
import tempfile
struct Target:
    var name: String
    def __init__(out self, name: String):
        self.name = name
    async def build(self) -> Int:
        with tempfile.TemporaryDirectory() as tempdir:
            await asyncio.sleep(0)
        return 1
def main() raises:
    var t = Target("x")
    print("ok")
```

Output: `[gimple_codegen] async function 'build' not eligible (pass 2): ...
not CallExpr` followed by `RuntimeError: cannot compile module: function(s) build
(async function(s), declared async def) ...`. This is the trigger in
`_targets.py`'s `_build_stencils`/`_compile`/`_parse`.

**Two findings that change the picture:**

1. Under the DEFAULT stack-switch backend (no `MOJO_CORO=cpp`) the same shapes do
   NOT refuse. They compile, with `tempfile.TemporaryDirectory()` emitted as a
   runtime stub (`/* tempfile.TemporaryDirectory() — raises: module not compiled */`)
   and `tempdir` bound to that stub's value. So the default backend silently
   binds a stub handle as `tempdir`. It fails loudly only when the stub runs.
   Not yet root-caused; the next step is to decide whether the default backend
   should refuse this shape the way the cpp backend does.
2. The refusal is the `_cpp_with_stmt` gate in `mojo/backend_gimple/cpp_core.py`
   (~5978). The gate is only reached through the cpp async eligibility pass.

**Next step (decision (a) from the earlier plan, still the recommended one):**
recognise `tempfile.TemporaryDirectory()` as an intrinsic guard, backed by an RAII
guard in `runtime/fire_async_runtime.cpp` (mkdtemp on enter, rmtree in the
destructor; coroutine frames run destructors on normal exit, exception, and frame
destruction, so cleanup survives an `await`). Needs a str-valued path binding for
`as tempdir`. Files: `runtime/fire_async_runtime.{cpp,h}`,
`mojo/backend_gimple/cpp_core.py` (`_cpp_with_stmt` intrinsic branch),
`mojo/backend_gimple/cpp_async.py` (`_cpp_with_guard_type_name`: resolve
`module.Type(...)` as a `MemberExpr` callee), `gimple_codegen.py` (allowlist
mirror). The downstream `_build_stencils`/`_compile`/`_parse` gaps (`TaskGroup`
named tasks, `pathlib.Path` ops, `task.get_name()`/`task.result()`, the `_llvm.run`
subprocess helpers) are still unmeasured and must be reproduced after the guard lands.

Verified this round: `test_regress_compile_fail_tools_jit_guard.py` (the reduced
refusal pin, passes) and `test_async_with_lock_guard.py` (3 passed, 0 failed,
covering the `BlockingScopedLock` allowlist this change touches). Not run: the
full `_targets.py` build (`test_regress_compile_fail_tools_jit_targets.py`), which
is a whole-closure compile too expensive for a light round.

(Older status entries preserved below for history.)
