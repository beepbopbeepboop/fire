# COMPILE_FAIL: Android/android.py

## Status (re-verified 2026-08-26, this session, master fast-forwarded to `9c0e7a8` — DOCUMENTED-NOT-FIXED, unchanged)

Fresh isolated `compile_to_gimple_with_cpp` probe (post this session's own
`filter(func, iterable)` coroutine-body codegen addition, gimple_cpp_
core.py/gimple_exprtypes.py — see COMPILE_FAIL_importlib_metadata___
init__.md's 2026-08-26 entry). Byte-for-byte identical refusal: the same
10 `async def` functions + `async_process` async generator, all rejected
by `_async_quick_eligible`'s await-shape pre-filter before any per-
function translation attempt (`create_subprocess_exec(...)`, `process.
communicate()`/`.wait()`, `stream.readexactly(...)`, a local `wait_for`
helper — none recognized). `filter()` is unrelated to this file's
blocker (no `filter(...)` calls anywhere in android.py). Confirmed
independently: real async-subprocess/stream I/O composition is a
genuine, feature-sized Awaitable-protocol extension to the async
codegen's suspension machinery, not a narrow fix — same conclusion as
every prior session across this campaign. Not attempted (would require
a new scheduler primitive: allocatable Future/pipe handles with waiter
queues and cross-coroutine wakeup, the same shared-machinery scope
`COMPILE_FAIL_asyncio_queues.md` documents in detail). No change.

Source file: `/Users/mrs/net/Python-3.14.6/Android/android.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-26, worktree agent-ae936147a68675d97 — independently re-derived from scratch, unchanged)

Re-read `_async_quick_eligible` (`gimple_exprtypes.py:184-255`) directly
rather than trusting prior doc conclusions, then ran a fresh isolated
`gimple_codegen.compile_to_gimple_with_cpp(do_imports=False)` probe.
Byte-for-byte identical refusal to every prior entry: the same 10
`async def` functions + `async_process` async generator. Confirmed from
the source itself that the whitelist covers only `asyncio.sleep(...)`,
calls to already-compiled sibling `async def`s, `asyncio.sock_recv(fd)`,
`create_task(...)`/`create_raising_task(...)`, and comptime-bracket
nested-async calls — `create_subprocess_exec(...)`,
`process.communicate()`/`.wait()`, `stream.readexactly(...)`, and a
local `wait_for` helper are all genuinely outside it. Widening this to
real subprocess/stream async I/O composition is the same feature-sized
Awaitable-protocol gap as `COMPILE_FAIL_asyncio_queues.md`. Not
attempted; no code change.

## Status (re-verified 2026-08-26, worktree-agent-a21934cd6fb7c6509 @ master `e60b9cd` — DOCUMENTED-NOT-FIXED, unchanged)

Fresh safety-wrapped `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Android/android.py`
against this worktree (fast-forwarded to master `e60b9cd`, the current
integration tip). Byte-for-byte identical refusal to every prior pass:
the same 10 `async def` functions + `async_process` async generator,
refused for the same reason (`await` targets outside
`_async_quick_eligible`'s whitelist: `create_subprocess_exec(...)`,
`process.communicate()`/`.wait()`, `stream.readexactly(...)`, a local
`wait_for` helper). Real async-subprocess/stream I/O composition
remains feature-sized; per this session's mandate (do not attempt the
tracked async-codegen feature project), not attempted. No change.

## Status (re-verified 2026-08-26, worktree fix/opencode-misc1 @ `e1e12bb` — DOCUMENTED-NOT-FIXED, unchanged)

Fresh safety-wrapped `python3 mojo.py build .../Android/android.py`
against this worktree (includes this session's dict-keyed %-formatting
landing, commit `e1e12bb`): byte-for-byte identical refusal to every
prior pass — the same 10 `async def` functions + `async_process` async
generator, refused before any per-function eligibility attempt because
their `await` targets (`create_subprocess_exec(...)`,
`process.communicate()`/`.wait()`, `stream.readexactly(...)`, a local
`wait_for` helper) are all outside `_async_quick_eligible`'s whitelist.
Real async-subprocess/stream I/O composition remains feature-sized; not
attempted. No change.

## Status (re-verified 2026-08-26, worktree fix/rest-remainder17 — DOCUMENTED-NOT-FIXED, unchanged)

Fresh full `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Android/
android.py` against this worktree (branched from master `1e0f3f2`,
`build/libmojostdlib.dylib` freshly rebuilt, 0 skips). Byte-for-byte
identical refusal to every prior pass: the same 10 `async def`
functions + `async_process` async generator, refused before any
per-function eligibility attempt because their `await` targets
(`create_subprocess_exec(...)`, `process.communicate()`/`.wait()`,
`stream.readexactly(...)`, a local `wait_for` helper) are all outside
`_async_quick_eligible`'s whitelist. This session's own fixes (dynamic
exception-value re-raise; MemberExpr-receiver `.append()`/`.clear()`/
`.add()`) are unrelated to the `await`-shape pre-filter. Real
async-subprocess/stream I/O composition remains feature-sized; not
attempted. No change.

## Status (re-verified 2026-08-25, worktree fix/rest-remainder14 — DOCUMENTED-NOT-FIXED, unchanged)

Fresh `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Android/android.py`
against this worktree (branched from master `f65502d`), run under the
safety-rule watcher. Byte-for-byte identical refusal to every prior
pass: the same 10 `async def` functions + `async_process` async
generator, refused before any per-function eligibility attempt because
their `await` targets (`create_subprocess_exec(...)`,
`process.communicate()`/`.wait()`, `stream.readexactly(...)`, a local
`wait_for` helper) are all outside `_async_quick_eligible`'s whitelist.
This is exactly the "real async-subprocess I/O" feature-sized case this
session's own mandate explicitly flags as out of scope. Not attempted.
No change.

## Status (re-verified 2026-08-25, worktree fix/rest-remainder12 — DOCUMENTED-NOT-FIXED, unchanged)

Re-ran an isolated `compile_to_gimple` check fresh, after this
session's 4 coroutine-emitter fixes landed elsewhere (see
COMPILE_FAIL_Apple___main__.md: `mojo_c_getenv`/platform/subprocess
runtime-call whitelist, zero-arg `print()`, string-repeat `*`, f-string
interpolation in `_cpp_expr`). None touch `_async_quick_eligible`'s
await-shape pre-filter, which is this file's actual blocker. Confirmed
byte-for-byte identical refusal to the 2026-08-23 entry below (same 10
async functions + `async_process` async-generator, same reason: their
`await` targets — `create_subprocess_exec(...)`, `process.communicate()`
/`.wait()`, `stream.readexactly(...)`, a local `wait_for` helper — are
all outside the whitelist). Real async-subprocess/stream I/O
composition remains feature-sized (same family as
COMPILE_FAIL_asyncio_queues.md's await-shape gap); not attempted.

## Status (re-verified 2026-08-23, wt09 fix/stdlib-mods `945af88` — DOCUMENTED-NOT-FIXED)

Re-ran the repro; byte-for-byte the same honest refusal as the 2026-08-09
verification below (10 async functions + 1 async generator refused
before any per-function eligibility attempt, because their `await`
shapes — `asyncio.create_subprocess_exec(...)`, `process.communicate()`,
`process.wait()`, `stream.readexactly(...)`, a local `wait_for` helper —
are all outside `_async_quick_eligible`'s whitelist). Confirmed again:
this is NOT warnings-only; it is a hard module-level refusal, and the
missing feature is a real async-subprocess/stream I/O composition layer
(process spawn with pipes wired into the compiled async runtime), which
is feature-sized work in the tracked async-codegen project (#95-135) —
not attempted this pass. Everything else in the file is warnings only
(unused-variable noise); no GCC errors remain behind the refusal.

## Status (updated 2026-08-06)

Re-ran; the original ~880-line GCC warning dump below is STALE (it was
truncated before ever reaching the real error). The actual, current
failure is an honest up-front refusal, not a GCC error:

```
Error building: cannot compile module: function(s) async_check_output,
find_device, find_pid, gradle_task, list_devices, logcat_task,
read_bytes, read_int, read_logcat, run_testbed (async function(s),
declared `async def`); async_process (async generator function(s),
declared `async def` AND contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, nor an event
loop / suspend-resume codegen for async functions, yet, so these cannot
be represented as compiled C without emitting silently wrong or broken
code; falling back to interpreting this module from source instead
```

This is an async/generator codegen refusal, part of the separate,
already-tracked compiled-generator/async-codegen project (tasks
#95-135) — not investigated further here per that project's scope.

### Re-verified 2026-08-09 against master `6feddbf` — still accurate

Reproduces byte-for-byte identical to the block above. `MOJO_DEBUG=1`
confirms these functions never even reach the per-function "not
eligible for C++ coroutine path" attempt (no debug line emitted for
any of them) — `_async_quick_eligible`'s cheap pre-filter silently
rejects them first, because their bodies `await` shapes outside its
recognized whitelist (`asyncio.sleep(<seconds>)`, `sock_recv`, a call
to another already-compiled `async def`, or `create_task(...)`):
`android.py` awaits `asyncio.create_subprocess_exec(...)`,
`process.communicate()`, `process.wait()`, `stream.readexactly(...)`,
and a local `wait_for(...)` helper — none recognized. Confirmed
structural (this codegen deliberately has no general subprocess/stream
async-I/O composition yet), no narrow fix available. Doc kept as-is.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Android/android.py: In function '_alloc_LogPriority':
/Users/mrs/net/Python-3.14.6/Android/android.py:123:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  123 |     if log:
      | ^   
/Users/mrs/net/Python-3.14.6/Android/android.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Android/android.py:137:11: warning: unused variable '_tag' [-Wunused-variable]
  137 | # Format the environment so it can be pasted into a shell.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Android/android.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Android/android.py:142:11: warning: unused variable '_tag' [-Wunused-variable]
  142 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Android/android.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Android/android.py:147:11: warning: unused variable '_tag' [-Wunused-variable]
  147 |         prefix = ANDROID_DIR / "prefix"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Android/android.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Android/android.py:162:11: warning: unused variable '_tag' [-Wunused-variable]
  162 |     for line in env_output.splitlines():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Android/android.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Android/android.py:171:13: warning: unused variable '_tag' [-Wunused-variable]
  171 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Android/android.py: In function 'log_verbose_132aaf':
/Users/mrs/net/Python-3.14.6/Android/android.py:621:7: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  621 |         raise ValueError(
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Android/android.py:612:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  612 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Android/android.py: In function 'delete_glob_0c85c9':
/Users/mrs/net/Python-3.14.6/Android/android.py:99:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   99 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Android/android.py: In function 'subdir':
/Users/mrs/net/Python-3.14.6/Android/android.py:127:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
  127 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Android/android.py:125:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  125 |     return subprocess.run(command, env=env, **kwargs)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Android/android.py:122:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  122 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Android/android.py:103:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  103 |     if not path.exists():
      |          ^~~
/Users/mrs/net/Python-3.14.6/Android/android.py: In function 'run_0211bc':
... (826 more lines)
```

Exit code: 1
Elapsed: 5.39s
