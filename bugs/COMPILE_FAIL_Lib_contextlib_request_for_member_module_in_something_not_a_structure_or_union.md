# COMPILE_FAIL: Lib/contextlib.py — request for member '__module__' in something not a structure or union

## Status (re-verified 2026-08-09, fresh against current master post-merge)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/contextlib.py`
against current master (this worktree's branch was rebuilt on top of
local master at fdd5e66, which includes all fixes from the intervening
sessions referenced elsewhere in `bugs/` — dict-subscript augmented
assignment, `del` statement, class-body enum attributes, for-loop
tuple-unpacking, etc.). None of those touched the async/generator
codegen path. Output is byte-for-byte the same failure class as the
2026-08-07 status below: the identical `RuntimeError` naming the same
11 async functions (`__aenter__` x3, `__aexit__` x4, `_exit_wrapper`,
`aclose`, `enter_async_context`, `inner`), same "no suspend/resume
state-machine transform" message. Still structural, still correctly
out of scope for a narrow fix — see the unchanged root-cause analysis
below. Checked whether the sibling fix that resolved
`bugs/COMPILE_FAIL_Lib_runpy_...md` (deleted 2026-08-09, function-
scoped-import link stub) or the socket.py `_lower_matmul` fix would
have any bearing here: neither is reachable, since this file fails
during `gen_module`'s async-function eligibility check, before any
link-time or matmul codegen is ever attempted. Not a shared root cause
with the other two docs in this cluster.

## Status (re-verified 2026-08-07, Track B continuation session)

The PERF hard bug this doc previously matched
(`bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`)
has since had its Phase 2 fix land — `Lib/contextlib.py` no longer
times out: `python3 mojo.py build .../contextlib.py` now completes in
~11s. It still does NOT build, but for a completely different reason:
a hard, honest `RuntimeError` refusal —

```
cannot compile module: function(s) __aenter__, __aenter__, __aenter__,
__aexit__, __aexit__, __aexit__, __aexit__, _exit_wrapper, aclose,
enter_async_context, inner (async function(s), declared `async def`)
```

`MOJO_DEBUG=1` shows the specific eligibility failures:
`__aenter__: every 'return' must carry a scalar value (int64_t/double/
_Bool), and all of them must agree on one consistent type` and
`__aexit__: *args/**kwargs parameters not supported for compiled async
functions`. This is the SAME class of limitation as
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md` (task
#147, explicitly out of scope per this session's assignment) and the
tuple-yield generator refusal documented in `bugs/CODEGEN_generator_
function_Lib_weakref.md`'s 2026-08-07 update — this codegen's C++20
coroutine translation for generators/async functions only supports a
narrow set of shapes (scalar yield/return values, no `*args`/`**kwargs`,
a fixed list of scalar/container parameter types), and `contextlib.py`'s
`@contextmanager`/`@asynccontextmanager`-heavy code hits several of
those restrictions at once (non-scalar `__aenter__` return, variadic
`__aexit__` params). Extending the coroutine codegen to support these
shapes is a genuinely large feature (would need real boxing/type-
erasure for non-scalar yield/return values and variadic-parameter
support in the coroutine frame), matching the profile of the other
generator/async-codegen limitations already flagged as out-of-scope for
this session — NOT attempted here.

## Status (updated 2026-08-06, historical — perf timeout above now fixed, current blocker is different)

Re-ran with a 150s timeout: TIMED OUT again (no output at all before
the timeout, not even the usual `drop stale export` dylib-link noise
that normally appears seconds in). Retried standalone with a longer
background run — still running after 9+ minutes before being killed
for this session's time budget, on a machine also running several
other agents' `mojo.py build` processes concurrently (this session is
one of many parallel worktree-agent-* sessions).

This matches the ALREADY-DOCUMENTED performance hard bug
`bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`
almost exactly — that doc's own confirmed repro is THIS EXACT FILE
(`Lib/contextlib.py`, chosen specifically because it imports `abc`,
`collections`, `functools`, `os`, `sys`, `types`, `warnings`, ...): a
`cProfile` run there shows `_walk_ast` called 4.47 MILLION times for
just 36 nested `gen_module` invocations, a confirmed quadratic-ish
blowup in the transitive-import compile path (do_imports=True) — not
a timing fluke or system load artifact, a real algorithmic issue with
a concrete root cause and phased fix plan already written up in that
doc.

The ORIGINAL `__module__`/"consolidated" note below is STALE (from an
older bug-tracking scheme predating the current `bugs/hard/` layout;
the referenced `consolidated/` directory no longer exists) — not
re-verified since the file doesn't get far enough to reach a GCC error
at all anymore, it never finishes compiling within any reasonable
timeout. Not investigated further here beyond confirming the PERF
hard-bug match — see that doc for the real fix plan.

## Original stale note (pre-2026-08-06, unverified)

**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

```
request for member '__module__' in something not a structure or union
```

This error pattern was tracked in:
`consolidated/COMPILE_FAIL_cc_error_request_for_member_x_in_something_not_a_structure_o.md`
(directory no longer exists as of 2026-08-06).

Source file: `/Users/mrs/net/Python-3.14.6/Lib/contextlib.py`
