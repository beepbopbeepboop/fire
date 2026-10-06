# COMPILE_FAIL: Android/android.py

## Status 2026-10-02 — the PREDICATE half of this doc's "next bounded action" is landed; the `asyncio.run` guard recognition and this file's blocker are not

The doc's 2026-10-01 entry named the next step precisely: *"teach
`asyncio.iscoroutine(x)` to lower to that same registry check (returning a real
`_Bool`), and let the `if` that guards `asyncio.run` be recognised as the
guard it is."* **The first of those two is done.**

### What landed — `asyncio.iscoroutine(x)` asks the live-handle registry

`runtime/fire_coro_gen.c` exports the check `__mojo_async_run_gen` already
performs, as a predicate of its own:

```c
_Bool __mojo_async_iscoroutine(int64_t genHandle)
{ return mgen_reg_has(genHandle) ? 1 : 0; }
```

`mojo/middle/coro.py`'s `_rewrite_asyncio_run` recognises the call and rewrites
it to that, in the same pass that already rewrites `asyncio.run` /
`create_task` / `.wait()`. No static inference is consulted and none is needed:
unlike `asyncio.run` this call does not DRIVE the value, it only asks about
it, so there is no reinterpretation to refuse, and the registry answers
correctly for every shape — including the ones `asyncio.run` still refuses.

**This was a silent wrong answer, not a missing feature.** Measured before
the change, on the shape this file writes:

```python
c = work(5)
if asyncio.iscoroutine(c):
    print('yes')
else:
    print('no')
```

printed `no`. `iscoroutine` had no lowering at all, so the guard the source
wrote evaluated **backwards** for a value that really was a coroutine: exit 0,
no diagnostic, and it reads as correct because the `else` branch of a guard
nobody is looking at is usually empty.

`asyncio.isawaitable` is deliberately NOT included: in CPython 3.14 it is
`inspect.isawaitable`, so a compiled answer under the `asyncio.` spelling —
where CPython raises `AttributeError` — would be the divergence, not the fix.
That is recorded in the recogniser's own docstring, because the two names
looking interchangeable is exactly what invites it back.

Two regressions, both at the layer that can tell the outcomes apart:

- `runtime/test_fire_coro_gen.c`'s
  `test_iscoroutine_answers_for_handles_and_non_handles` (driven by the
  `coro` suite, 20/20 across both Layer-3 backends at -O0 and -O2): NULL, a
  small integer and a plausible pointer answer 0; a REAL live handle answers
  1; and — the half a static table could not give — the same handle answers 0
  again once destroyed, which is what makes the registry rather than an
  address->type table load-bearing.
- `test_runtime_diff.py`'s `asyncio_iscoroutine_predicate` (interp-vs-JIT):
  both branches of the guard, so a predicate that always answered `True`
  cannot pass it.

### What is still open — this file does not build, and this does not move it

**`Android/android.py` still fails with the same refusal as before**, at the
same site, `Android/android.py:1028`:

```
cannot compile module: asyncio.run(...) requires either a bare call to a
supported compiled async function, or a name this function binds from such a
call, as its argument -- got a non-call expression that is not a known
coroutine handle, and driving it would reinterpret an arbitrary value as a
coroutine handle
```

`result = dispatch[context.subcommand](context)` is a call through a dict
SUBSCRIPT, so the callee is chosen at runtime and no static evidence about it
exists. That refusal is correct and stays.

What is left of the doc's next bounded action is therefore the second half,
and it is the half that would actually matter:

1. **Recognise the guard.** `if asyncio.iscoroutine(x): asyncio.run(x)` is a
   guard the source wrote, and with the predicate now real it is a check the
   compiler can read: inside the `then` body, `x` is a live handle *by
   construction*, so `asyncio.run(x)` there needs no static inference about
   where `x` came from. That is control-flow-sensitive reasoning, and it is a
   design question rather than a missing branch — which is what the 2026-10-01
   entry said and is still what it is.
2. **Then the dynamic callee.** Even with (1), `dispatch[...]` yields a value
   whose provenance no static pass can name, so the *bridge* still has to be
   reachable for a non-statically-named callee. That is the same widening the
   refusal's own wording names ("would reinterpret an arbitrary value as a
   coroutine handle") and it stays refused until the registry check is what
   stands between the value and `MojoGen *` — which, as of this entry, is now
   true for the predicate and still only half-true for `asyncio.run`.
3. **Then the 9 async functions** (`_async_quick_eligible`'s whitelist has no
   `asyncio.create_subprocess_exec` / `process.communicate()` /
   `stream.readexactly(...)`), which remain the feature-sized work this doc
   has always said they are. Unchanged.

## Status 2026-10-01 — unchanged; the blocker is one dynamic callee, and the runtime half that would handle it already exists

Fresh `python3 fire.py build /Users/mrs/net/Python-3.14.6/Android/android.py`
on this tree: **exit 1**, one refusal, the same one the two most recent
substantive entries below describe:

```
cannot compile module: asyncio.run(...) requires either a bare call to a
supported compiled async function, or a name this function binds from such a
call, as its argument -- got a non-call expression that is not a known
coroutine handle, and driving it would reinterpret an arbitrary value as a
coroutine handle
```

The site is `Android/android.py:1028`, inside a dispatch table:

```python
dispatch = {"configure-build": configure_build_python, ..., "env": env}
result = dispatch[context.subcommand](context)
if asyncio.iscoroutine(result):
    asyncio.run(result)
```

`result` is bound from a call through a dict SUBSCRIPT, so it is neither a
bare call to a known `async def` nor a name this function's own body binds
from one — the two shapes `_scan_handle_vars` recognises. Nothing about that
is fixable by widening the recogniser: the callee is chosen at runtime, so no
static evidence exists, and the refusal's own wording ("would reinterpret an
arbitrary value as a coroutine handle") is the reason it must stay.

The seven "re-verified, DOCUMENTED-NOT-FIXED, unchanged" entries that used to
sit above the substantive ones are removed, per CLAUDE.md: they are the exact
pattern a `bugs/` entry is supposed to stop being.

### The observation worth keeping

The refusal is about COMPILATION, and the honest answer to it already exists
one layer down: `__mojo_async_run_gen` checks its argument against the live
handle registry and raises Python's own `ValueError: a coroutine was
expected` for anything that is not a live handle (see the 2026-09-27 entry's
"Half 2"). So the runtime can already do the right thing with a value the
compiler cannot vouch for; the compiler simply refuses to emit the call
rather than emit a call the runtime will police.

That makes the next step narrower than "compiled async" suggests: teach
`asyncio.iscoroutine(x)` to lower to that same registry check (returning a
real `_Bool`), and let the `if` that guards `asyncio.run` be recognised as
the guard it is. That is control-flow-sensitive reasoning about a guard the
source already wrote, which is a real design question and not a narrow fix —
but it is a bounded one, and it is the reason this file is worth another pass
rather than being closed as feature-sized.

## Status (2026-09-27, later — the `asyncio.run(<non-literal>)` bridge is built: BOTH halves, the static inference and the checked runtime entry point)

The entry below correctly identified that this needed two halves and that
"either half alone would be a guess". Both are landed.

### Half 1 — static inference (`mojo/middle/coro.py`)

`asyncio.run(x)` now also accepts a **name** this function's own body binds
from a coroutine-producing call, not just a bare call. The evidence is a new
`_scan_handle_vars(fn, coro_names)`: a name bound from `create_task(...)` /
`create_raising_task(...)`, or from a bare call to an `async def` this module
actually compiled (a new `_ASYNC_FN_NAMES` registry, filled from the same
`_eligible_async*` verdicts that decide whether the function is lowered at
all — so "this module compiled it" and "a `__mgco_<name>_start` exists for
the ordinary call path to reach" are the same fact by construction).

Everything else is still refused, and that refusal is the load-bearing part:
a literal, a parameter, a name bound from an arbitrary expression, and a name
bound from a call to a function that is *not* in `_ASYNC_FN_NAMES` all keep
the honest "cannot compile module" error, because driving them would
reinterpret an arbitrary int64_t as a `MojoGen *`. Deliberately same-module
only: a cross-module `async def` callee is not visible to this pass, so a var
bound from one is still refused rather than guessed.

The two-step idiom this unlocks is the one `android.py` actually uses:

```python
c = work(5)          # already lowered to __mgco_work_start(...) by the
print(asyncio.run(c))   # ordinary call path; `c` really is a live handle
```

Also fixed in the same code, a one-token latent bug in the neighbouring
`_scan_task_vars`: the name-extraction line tested `isinstance(s.target, ...)`
against the **statement**, so a bare `task = create_task(f())` with no `var`
keyword never registered and `<task>.wait()` was refused for a shape it
supports.

### Half 2 — the checked runtime entry point (`runtime/fire_coro_gen.c`)

`__mojo_async_run_gen` no longer trusts its caller. A new live-handle
registry — added at the single allocation site (`mgen_new_impl`) and removed
at the single free site (`__mojo_gen_destroy`), so it describes exactly the
live handles and a recycled address cannot be mistaken for a stale one — backs
a check at the top of the function. A value that is not a live handle raises
`ValueError: a coroutine was expected`, Python's own answer for
`asyncio.run(<not a coroutine>)`, with the exception tag spelled as the number
`663468903` so a compiled `except ValueError:` actually catches it. Before
this, the value was cast straight to `MojoGen *` and `->done` was read out of
whatever memory the integer pointed at.

The registry is a hand-rolled chained set, not `mojo_set_*`: that translation
unit deliberately does not include `fire_runtime.h` (see its own header
comment), and the population is one node per live coroutine handle.

### Regression

- **Compiler level**, `test_runtime_diff.py`'s `asyncio_run_of_a_name` (a
  registered test, interp-vs-JIT): both spellings, `asyncio.run(work(7))` and
  `asyncio.run(c)`, asserting the real return value.
- **Runtime boundary**, `runtime/test_fire_coro_gen.c`'s
  `test_run_gen_rejects_non_handle`, driven directly by the `coro` test
  (20/20 across both Layer-3 backends at -O0 and -O2). It has to be driven at
  the C level: every shape the compiler can get wrong is *already* refused
  statically, so a test through the compiler could only ever exercise the
  already-correct path. It checks three non-handle shapes (NULL, a small
  integer, a plausible heap address) and asserts both the exception type and
  its message.

### What is still open for this file

`_async_quick_eligible` still refuses all 9 remaining async functions
(`async_process`, `async_check_output`, `list_devices`, `find_device`,
`find_pid`, `logcat_task`, `read_logcat`, `gradle_task`, `run_testbed`),
because their `await` targets are `asyncio.create_subprocess_exec(...)`,
`process.communicate()`, `process.wait()`, `stream.readexactly(...)` and a
local `wait_for` helper. That remains the feature-sized work (a real
async-subprocess/stream composition layer, the same project
`COMPILE_FAIL_asyncio_queues.md` describes), and **this doc does not claim
otherwise**. The bridge above does not move that frontier: `android.py`'s own
`result` comes from `dispatch[context.subcommand](context)`, a
dynamically-obtained coroutine with no statically-named callee, so it is
still (correctly) refused by half 1.

## Status (2026-09-27 — the async SUBSET is now inventoried by measurement, and one real gap in it is closed; the file's first blocker has MOVED and is new)

Every prior entry in this doc is a "verified unchanged, not attempted"
re-verification. This entry replaces that with measured data, because the
frontier has genuinely moved and the recorded blocker text no longer
describes what actually stops the file.

### The file's FIRST blocker is no longer the async await shapes

`python3 fire.py build .../Android/android.py` now fails with:

```
cannot compile module: asyncio.run(...) requires a bare call to a
supported compiled async function as its argument -- got a non-call
expression, which has no coroutine handle to drive
```

`android.py:1026` is `asyncio.run(result)`, where `result` came from
`dispatch[context.subcommand](context)` — a dynamically-obtained
coroutine, not a bare call. `gimple_gen_coro._rewrite_asyncio_run`
refuses this on purpose (the argument would otherwise be passed through
and reinterpreted as a `MojoGenerator *` — a real silent miscompile the
check was added to prevent), and the doc had no entry for it because
until now the 10 async functions were refused EARLIER, at a
whole-module stage that fired first.

**It is genuinely not a one-liner.** The guard is correct as written:
`asyncio.run(x)`'s runtime bridge drives a coroutine handle, and
`result` here may or may not BE one (`if asyncio.iscoroutine(result):`
two lines above). Accepting a non-literal needs (a) a static type
inference for "this local holds a coroutine handle", which
`dispatch[context.subcommand](context)` does not provide, and (b) a
CHECKED runtime entry point that is safe on a non-coroutine value, which
`__mojo_async_run_gen` is not. Either half alone would be a guess.

### The async subset, measured

`_async_quick_eligible` still refuses all 9 remaining async functions
(`async_process`, `async_check_output`, `list_devices`, `find_device`,
`find_pid`, `logcat_task`, `read_logcat`, `gradle_task`, `run_testbed`)
— the doc's recorded list is accurate — and they are refused for the
documented reason: their `await` targets are
`asyncio.create_subprocess_exec(...)`, `process.communicate()`,
`process.wait()`, `stream.readexactly(...)` and a local `wait_for`
helper, none of which is in the whitelist. That remains the
feature-sized work (a real async-subprocess/stream composition layer, the
same project `COMPILE_FAIL_asyncio_queues.md` describes). **This doc does
not claim otherwise.**

What the subset *does* support, each verified by building and running a
minimal program (not by reading the whitelist):

| supported | notes |
|---|---|
| `await asyncio.sleep(<scalar>)` | |
| `await <sibling compiled async fn>(...)`, with arguments | source order required |
| `asyncio.create_task(...)` + `await <task>` | |
| `await` under `if` / `while` / `for` / `try` | at any nesting depth |
| `asyncio.run(<bare call>)` | |
| **`await` nested inside a call's argument list** | **closed 2026-09-27, see below** |

### CLOSED: an `await` inside a call's argument list

`for i in range(3): results.append(await fetch(i))` was refused at ANY
nesting depth, on both coroutine backends — both are STATEMENT emitters
and cannot suspend from the middle of a C expression. The hand-split
form (`v = await fetch(i); results.append(v)`) compiled fine, so the gap
was purely the nesting and not the loop, the method call, or the
container.

`mojo/middle/coro.py`'s new `hoist_awaits_from_call_args` rewrites the
provably order-preserving shape into exactly that, and is called from the
ONE shared eligibility chokepoint (`_eligible_async_common`) so the A3
and C++20-coroutine backends cannot drift. Only three conditions
qualify, and they exist because hoisting moves the awaited expression
earlier in its statement: the `await` must be the SOLE argument of its
enclosing call, that call must be the only `CallExpr` in the whole
statement, and the awaited expression must be a call / bare name /
attribute chain. Anything else is left completely untouched and falls
back to the honest whole-module refusal. Regression:
`test_runtime_diff.py`'s `await_inside_call_argument`, four placements
(top level, `if`, `while`, `for`) asserting real VALUES, not just
compilation; it fails at `435cc71`.

Two things that transform got wrong first, both worth recording because
both failed SILENTLY (compiled, linked, ran, printed the wrong answer)
and both are now guarded by comments in the code:

- the temporary must be named with a plain identifier; a leading
  double underscore (`__await_tmp_1`) is not resolvable as a local by
  the A3 backend and became a constant 0;
- the rewritten statement list MUST be written back onto `fn.body`. The
  transform returns a LONGER list; dropping the return value still
  rewrote each statement's own `.value` in place, so the body read a
  temporary that was never declared — and because the suspension point
  was inside that missing statement, the await VANISHED rather than
  erroring.

### Next bounded action

Unchanged in direction, now with a measured floor:

1. The checked `asyncio.run(<non-literal>)` bridge (a coroutine-or-not
   test at the runtime boundary plus the static inference to feed it).
2. Then the async-subprocess/stream composition layer, which is the real
   blocker for all 9 functions and is not attempted here.

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
