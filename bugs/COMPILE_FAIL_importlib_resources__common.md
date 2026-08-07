# COMPILE_FAIL: Lib/importlib/resources/_common.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; the original GCC-warning dump below is STALE (compilation now
gets further and fails at LINK time, not with these warnings). Current
failure is two separate undefined symbols at link:

```
link failed: Undefined symbols for architecture arm64:
  "_wrap_spec", referenced from:
      _from_package_0c85c9 in ...o
ld: symbol(s) not found for architecture arm64
```
```
Linking failed: Undefined symbols for architecture arm64:
  "_next", referenced from:
      __infer_caller in _common.o
ld: symbol(s) not found for architecture arm64
```

Root-caused both, NOT fixed (see below):

1. `_wrap_spec`: `from_package()`'s body does a FUNCTION-SCOPED (not
   top-level) relative import: `from ._adapters import wrap_spec`, then
   calls `wrap_spec(package)`. This codegen's cross-module import
   resolution appears to only wire up real symbol references for
   TOP-LEVEL `import`/`from X import Y` statements — a local import
   inside a function body still gets a call site emitted (`_wrap_spec
   (...)`, unmangled, as if it were a same-module or already-resolved
   name) but no corresponding real definition/extern declaration ever
   gets pulled in from `importlib/resources/_adapters.py`, so the
   linker never finds it.

2. `_next`: `_infer_caller()` computes `callers =
   itertools.filterfalse(...)` (a genuine Python iterator object, not a
   `MojoList`/`MojoDict`/generator this codegen models) then calls the
   builtin `next(callers)`. The `next()` builtin appears to be assumed
   always resolvable, without going through the "unknown name" auto-
   stub protection (`self._auto_stubbed`/`_emitted_unresolved_stub_syms`
   in `gimple_codegen.py`) that normally guards against exactly this
   "call a name that turns out to have no real definition" shape — so
   it emits a direct, unmangled `_next(...)` call site with no fallback
   and no stub, which the linker then can't resolve since nothing
   anywhere defines a C symbol literally named `next`/`_next` for a
   generic-iterator receiver.

## Not fixed

Both are real, narrow-looking gaps, but neither was attempted: #1 is
cross-module import-resolution machinery (function-scoped imports are
common throughout the stdlib — CPython's own style guide recommends
them for deferred/circular-import avoidance, exactly as this file's own
comment `# deferred for performance (python/cpython#109829)` states),
and #2 touches builtin-call resolution for `next()`, which — unlike a
`for` loop over a known container — isn't obviously narrow once a
receiver can be an arbitrary Python iterator (itertools object,
generator, custom `__next__`, ...). Both plausibly recur across many
other stdlib files (function-scoped imports especially). Given this
session's standing caution around call-resolution/type-inference
changes with hard-to-predict blast radius, left undone for a dedicated
pass rather than attempted here.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 |     # zipimport.zipimporter does not support weak references, resulting in a
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:71:11: warning: unused variable '_tag' [-Wunused-variable]
   71 |         return None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:76:11: warning: unused variable '_tag' [-Wunused-variable]
   76 | def resolve(cand: Optional[Anchor]) -> types.ModuleType:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:91:11: warning: unused variable '_tag' [-Wunused-variable]
   91 |     """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:100:13: warning: unused variable '_tag' [-Wunused-variable]
  100 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function '_alloc_package_to_anchor_wrapper_env':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:229:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function 'package_to_anchor_wrapper':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:51:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   51 | @package_to_anchor
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:48:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   48 |     return wrapper
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:40:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   40 |                 DeprecationWarning,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:273:1: warning: label 'bb_6' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:46:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   46 |         return func(anchor)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:268:1: warning: label 'bb_3' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:263:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:261:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:260:10: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:259:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:258:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:257:10: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:256:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:255:9: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:254:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:253:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:252:10: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:251:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
... (261 more lines)
```

Exit code: 1
Elapsed: 10.39s
