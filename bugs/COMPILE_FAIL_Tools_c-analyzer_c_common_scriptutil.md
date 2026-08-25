# COMPILE_FAIL: Tools/c-analyzer/c_common/scriptutil.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/scriptutil.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-25, branch fix/opencode-pkgutil — shared consumption-ordering fix landed; per-function reasons refined; refusal set unchanged)

The shared "generator-consumption ordering" machinery (this doc's
2026-08-23 note's `filter_filenames`/`main_for_filenames` refusals) is
now FIXED in shared source (commit `9ea2749` on fix/opencode-pkgutil):
the generator retry loop runs to a fixed point instead of a hard-coded
3 passes, coroutine-body consumption paths pad omitted trailing args
from the consumed generator's registered defaults, a silent direct-call
default-mispad (`prod(3)` vs `def prod(n, step=10)` ran with step=0)
is fixed, and refusal reasons are latest-wins so stale "defined LATER"
text no longer masks real blockers. Forward consumption of an ELIGIBLE
later-defined generator now works at any depth, verified end-to-end
(new tests; gates 253/253, 76/76, selfhost clean, stdlib dylib 0 skips).

Re-ran this file post-fix: same five-function refusal SET, but two
reasons are now more precise (latest-wins reports each function's real
final blocker, not pass 1's):

- `_iter_filenames`: NOW refuses on `onempty = Exception('no filenames
  provided')` — constructing a builtin-exception INSTANCE as a value in
  a generator body has no lowering (unresolved callee `Exception(...)`)
  — and only THEN hits the already-documented items (`iterutil.*`
  module-member calls, `fsutil.USE_CWD`, tuple-target consumption of
  `iterutil.iter_many(...)`). The 2026-08-10 lambda gap itself is gone
  (zero/single-param lambda support landed since).
- `filter_filenames` / `main_for_filenames`: still refuse consuming
  `_iter_filenames(...)`, but this is now MOOT-ordering: an eligible
  later-defined callee resolves automatically post-fix, and
  `_iter_filenames` is never eligible for its own reasons above. These
  two unblock only when `_iter_filenames` does.
- `track_progress_compact`: unchanged (`**mark_kwargs` spread forwarded
  to a known GENERATOR callee — separate documented gap).
- `track_progress_flat`: newly visible (was masked behind siblings'
  earlier refusals): its body calls `print(...)` inside the generator
  body — print is not among the coroutine-body emitter's supported
  callees.

All shapes remain within tracked coroutine-codegen project scope; doc
kept open.

## Status (updated 2026-08-23 — BOTH 2026-08-10 blockers confirmed gone; new refusal chain documented)

Re-ran against current master tip (`626f3f0`). Both blockers the
2026-08-10 update below listed are confirmed no longer reached:
`main_for_filenames` is not refused for its tuple-valued yield (the
tuple-yield support holds), and `_iter_filenames`'s `check =
(lambda: True)` is not refused either (zero-arg lambda support landed
2026-08-20 per the fsutil doc's update; `_iter_filenames` produces no
refusal at all in this run's MOJO_DEBUG output).

The build now aborts on a DIFFERENT generator, with a new precise
refusal:

```
[gimple_codegen] generator 'track_progress_compact' not eligible for
C++ coroutine path, falling back to honest refusal: a `*`/`**`-unpack
call argument is not supported in a compiled generator/coroutine body
Error building: cannot compile module: function(s)
track_progress_compact ...
```

Root cause: `track_progress_compact`'s body does `marks =
iter_marks(groups=groups, **mark_kwargs)` — a literal keyword PLUS a
`**kwargs` spread forwarded to a statically-known GENERATOR callee.
The existing narrow kwargs-forwarding helper (`_cpp_try_kwargs_forward_call`,
gimple_cpp_core.py) deliberately excludes generator callees (compiled
generators have no directly-callable C symbol, only the
`_start`/`_resume`/`_value` API), and there is today NO
generator-object-value representation in a coroutine body at all
(no way to hold `marks`, and `next(marks)` two lines later has no
lowering either), so this shape is refused honestly rather than
mis-lowered.

Also visible in MOJO_DEBUG (retried on later passes but not the final
aborting name): `filter_filenames` and `main_for_filenames` refuse
consuming `_iter_filenames(...)` — "does not consume a generator this
compile has itself already translated ... or it's defined LATER in this
module" — the same source-ordering constraint that binds all
cross-generator consumption here. All shapes remain within the tracked
coroutine-codegen project scope; not attempted this session.

## Status (updated 2026-08-10 — `main_for_filenames`'s tuple-valued yield now FIXED; `_iter_filenames` remains refused for an unrelated, non-tuple reason)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`). Re-verified: `main_for_filenames` is no longer in the
refusal list — it now compiles past the eligibility gate. Only
`_iter_filenames` remains refused, and NOT for a tuple-arity/shape
reason:

```python
def _iter_filenames(filenames, process, relroot):
    ...
    check = (lambda: True)
    for filename, ismany in iterutil.iter_many(items, onempty):
        relfile = fsutil.format_filename(filename, relroot, fixroot=False)
        yield filename, relfile, check, ismany
```

The 4-tuple yield's THIRD element, `check`, is bound to a `lambda: True`
closure. `_cpp_expr` (the coroutine-body expression lowering) has no
case for `LambdaExpr` at all — attempting to box it would need a real
value representation for a closure, which this narrow scalar/pointer
coroutine-body model doesn't have. Confirmed via `MOJO_DEBUG=1`: the
refusal is now the honest, precise `unsupported expression in generator
body: LambdaExpr` (raised by `_cpp_expr`'s own existing exhaustive
fallback, not anything new added this session) — not a tuple-arity/type
mismatch. Unrelated to and unaffected by this fix. Doc kept open (not
deleted) — 1 of 2 generators fixed, but the file still doesn't build.

## Status (re-verified 2026-08-09)

Re-ran against current master (`python3 mojo.py build .../c_common/
scriptutil.py`); still an honest up-front refusal, not a GCC error, now
naming both generator functions in the file:

```
Error building: cannot compile module: function(s) _iter_filenames,
main_for_filenames (generator function(s), contain a `yield`/`yield
from`) — this codegen compiles every function into a single
straight-line C function and has no suspend/resume state-machine
transform for generators, nor an event loop / suspend-resume codegen
for async functions, yet, so these cannot be represented as compiled C
without emitting silently wrong or broken code; falling back to
interpreting this module from source instead
```

With `MOJO_DEBUG=1`, the two functions fail the C++20-coroutine
eligibility pre-check for two DIFFERENT reasons, both manifestations of
the same already-tracked "coroutine codegen has much weaker type
inference/expression coverage than the ordinary function path" gap
(the same root cause independently confirmed this session for the
sibling files `c_analyzer/__init__.py`, `c_analyzer/__main__.py`,
`c_analyzer/info.py`):

```
generator 'main_for_filenames' not eligible for C++ coroutine path,
falling back to honest refusal: main_for_filenames: every `yield` must
carry a value, and all values must agree on one scalar type
(int64_t/double/_Bool)

generator '_iter_filenames' not eligible for C++ coroutine path,
falling back to honest refusal: unsupported expression in generator
body: LambdaExpr
```

- `main_for_filenames` (line 542) does `yield filename, relfile` — a
  2-tuple-valued yield. The coroutine promise machinery
  (`_gen_cpp_generator_unit`) only supports a single scalar
  (`int64_t`/`double`/`_Bool`) yield-value type across the whole
  function, exactly the "tuple-valued yields aren't representable at
  all" gap.
- `_iter_filenames` (line 555) assigns `check = (lambda: True)` inside
  the generator body. The compiled generator/coroutine body is lowered
  by a SEPARATE, narrower expression dispatcher (`_cpp_expr`,
  `gimple_codegen.py` ~line 23198) than the ordinary function path's
  general expression lowering (`_lower_LambdaExpr`, ~line 14905, which
  DOES support lambda-lifting) — `_cpp_expr` has no `LambdaExpr` case
  at all and falls through to the generic "unsupported expression in
  generator body" raise (~line 23851). Same underlying "coroutine path
  has much less expression/type coverage than the ordinary path"
  structural gap, different specific symptom (unsupported expression
  kind rather than unsupported yield-value shape).

Both are the same deliberately-deferred, already-tracked compiled-
generator/async-codegen project (see `bugs/CODEGEN_generator_function_
Lib_*.md`) — not attempted here, out of scope for a narrow fix (would
require either extending the coroutine promise to carry a tuple/struct
value type, or teaching the generator-body expression dispatcher to
lift lambdas, both real feature work on shared coroutine-codegen
machinery, not a one-spot stub).

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py: In function 'configure_logger_7a6366':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:86:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:85:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:83:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:82:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:78:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:72:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:63:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   63 |         print(*args, **kwargs)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:62:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   62 |             return
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py: In function '_alloc_hide_emit_errors_restore_env':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:44:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   44 |     Rather than printing a message describing the error, we show nothing.
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py: In function 'hide_emit_errors_restore':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:58:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   58 |         self.verbosity = verbosity
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:56:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   56 | class Printer:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:55:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   55 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:54:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   54 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:53:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   53 |     return restore
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:52:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   52 |         logging.raiseExceptions = orig
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py: In function 'hide_emit_errors':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:57:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   57 |     def __init__(self, verbosity=VERBOSITY):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py: In function 'logging_Printer___init__':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:60:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   60 |     def info(self, *args, **kwargs):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:58:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   58 |         self.verbosity = verbosity
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py: In function 'logging_Printer_info':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:65:1: warning: label 'bb_4' defined but not used [-Wunused-label]
... (1070 more lines)
```

Exit code: 1
Elapsed: 14.62s
