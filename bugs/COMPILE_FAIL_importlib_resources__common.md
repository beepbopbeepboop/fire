# COMPILE_FAIL: Lib/importlib/resources/_common.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (RESOLVED 2026-08-07)

**Builds and links successfully now.** `python3 mojo.py build
.../_common.py` succeeds end-to-end, and `driver.compile_program(...)`
(link mode) returns `rc=0` directly. BOTH undefined-symbol findings
below are fixed by the SAME root-cause fix:

- `_wrap_spec` (finding #1): fixed as part of
  `bugs/hard/CODEGEN_function_scoped_import_call_unresolved_at_link.md`
  — see that doc for the full mechanism (a link-mode preamble branch
  was emitting a bare, definition-less `extern` for a function-scoped
  import whose defining module has no buildable C signature, instead
  of the weak-stub-definition convention `do_imports=True` already
  used for the identical situation).
- `_next` (finding #2, `next(itertools.filterfalse(...))`): turned out
  to be the EXACT SAME preamble branch, not a separate builtin-
  resolution gap as originally guessed — `next` reaches
  `self.imported_symbols` with no `'signature'` the same way an
  unresolvable function-scoped import does, so the same fix covers it
  incidentally. Confirmed fixed (`_next` now gets a weak stub instead
  of a bare extern) without any additional change specific to
  builtin-call resolution.

Full 5-part quality gate passed (test_gimple.py 247/0,
test_module_cache.py 76/0, check-selfhost clean, stdlib dylib rebuild 0
skips, compile_stdlib.py 664/664 0 unexpected) — see the hard-bug doc
for the actual gate output.

## Status (updated 2026-08-06, historical — both link failures now fixed, see above)

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

Neither was attempted. #1 is now written up as a full hard bug —
`bugs/hard/CODEGEN_function_scoped_import_call_unresolved_at_link.md`
— since `bugs/COMPILE_FAIL_Lib_runpy_request_for_member_module_in_something_not_a_structure_or_union.md`
turned out to share the EXACT same mechanism (a second, independent
confirmed instance), making this a genuine recurring gap, not a one-off.
#2 touches builtin-call resolution for `next()`, which — unlike a `for`
loop over a known container — isn't obviously narrow once a receiver
can be an arbitrary Python iterator (itertools object, generator,
custom `__next__`, ...); left undocumented as its own hard bug for now
(only one confirmed instance so far) but flagged here for whoever picks
up #1, since the two may share more machinery than currently known.

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
