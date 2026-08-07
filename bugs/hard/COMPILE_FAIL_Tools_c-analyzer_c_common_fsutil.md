# COMPILE_FAIL (hard): Tools/c-analyzer/c_common/fsutil.py

## Status (updated 2026-08-07)

**NOT resolved** (task #140), despite the root-cause bug this doc
points to (`CODEGEN_generator_recursive_yield_from_no_arg_forwarding.
md`, task #138) now being FIXED. Confirmed via `MOJO_DEBUG=1`: `iter_
files` is no longer blocked by the arg-forwarding/self-recursion gap —
but this file STILL fails to compile, now hitting a DIFFERENT, genuinely
separate, previously-MASKED blocker in the same function:
```
[gimple_codegen] generator 'iter_files' not eligible for C++ coroutine
path, falling back to honest refusal: unsupported expression in
generator body: LambdaExpr
```
`iter_files`'s own body (line 285 of the real file) has:
```python
get_files = (lambda *a, **k: _walk(*a, walk=_files, **k))
```
a lambda expression (with its own `*args`/`**kwargs` forwarding)
assigned to a local — entirely unrelated to yield-from/self-recursion,
and out of this narrow generator-body codegen's scope on its own
merits. This was always there; the arg-forwarding bug just refused
`iter_files` earlier (via the blanket whole-module pre-check) before
ever reaching this line. Not investigated/fixed further — a distinct,
new potential hard-bug candidate (LambdaExpr support inside a compiled
generator body) for a future session, not in scope for task #138's fix.

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py`

Root cause (current): see
`CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md` in this
directory (that file has the minimal test case). Summary: `iter_files` is a
generator using a recursive `yield from iter_files(...)` call with
keyword-only parameters; this file hits a blanket "generator not supported"
pre-check and fails to compile before even reaching the C++ coroutine
codegen.

**This is NOT the bug originally reported here.** The original report
(below, preserved for history) was about `create_backup`'s `exc.filename`
attribute access ("request for member 'filename' in something not a
structure or union"). That specific error **no longer reproduces** — the
generator pre-check above now fires first and blocks the whole module
before `create_backup` is ever reached, masking whatever the original
symptom's current status actually is (fixed or still-latent — unconfirmed
either way).

## Current error (2026-08-05, after commit 12ff719)

```
$ python3 mojo.py build Tools/c-analyzer/c_common/fsutil.py
Error building: cannot compile module: function(s) iter_files (generator function(s), contain a `yield`/`yield from`) — this codegen compiles every function into a single straight-line C function and has no suspend/resume state-machine transform for generators, nor an event loop / suspend-resume codegen for async functions, yet, so these cannot be represented as compiled C without emitting silently wrong or broken code; falling back to interpreting this module from source instead
```

Exit code: 1 (despite the message claiming a fallback, `mojo.py build`
does not actually fall back — no object file is produced).

## Original report (2026-07-xx, superseded — kept for history)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py: In function 'create_backup_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:44:14: error: request for member 'filename' in something not a structure or union
   44 |         return os.path.abspath(filename)
      |              ^~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/fsutil.py:47:8: error: assignment to 'int64_t' from 'char *' makes integer from pointer without a cast [-Wint-conversion]
   47 |     return _fix_filename(filename, relroot)
      |        ^
```

(Both the reported line and error text as they existed then; the file
compiled far enough to reach `create_backup`/`fix_filename` at that time,
which is no longer the case now that the generator check blocks it
earlier.)
