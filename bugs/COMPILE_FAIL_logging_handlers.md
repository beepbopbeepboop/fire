# COMPILE_FAIL: Lib/logging/handlers.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (2026-08-07): FIXED

Re-ran; the 2026-08-06 `invalid conversion in gimple call` error (below)
no longer reproduces at all — other fixes landed earlier this session
got past it. The build advanced to a NEW failure, a link-time undefined-
symbol error:

```
$ python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py
Undefined symbols for architecture arm64:
  "_TimedRotatingFileHandler_handleError", referenced from: ...
  "_TimedRotatingFileHandler__open", referenced from: ...
  "_RotatingFileHandler_namer", referenced from: ...
  "_RotatingFileHandler_rotator", referenced from: ...
  ... (same pattern for RotatingFileHandler and TimedRotatingFileHandler)
ld: symbol(s) not found for architecture arm64
```

### Root cause

`TimedRotatingFileHandler`/`RotatingFileHandler` both inherit from
`BaseRotatingHandler(logging.FileHandler)` — a class in the SAME file
inheriting from a class in a DIFFERENT module, reached via a bare
`import logging` (not `from logging import FileHandler`). Because bare
`import logging` never pulls `logging/__init__.py`'s `StructDef`s into
this compile's known-struct set, `FileHandler`/`Handler` are never
resolved, so `BaseRotatingHandler` correctly lands in
`self._structs_with_unresolved_base` (an existing mechanism — see that
set's own doc comment in `gimple_codegen.py`, `gen_module`) — but that
computation only checked each struct's OWN DIRECT bases, not the whole
chain. `TimedRotatingFileHandler(BaseRotatingHandler)`'s direct base
name (`BaseRotatingHandler`) IS a known `StructDef` (defined right there
in `handlers.py`), so the old direct-only check never flagged
`TimedRotatingFileHandler`/`RotatingFileHandler` themselves, even though
they inherit (and call — `self.handleError(...)`, `self._open()`) the
exact same never-defined-anywhere methods through that chain.

The practical effect: `_lower_struct_method_call`'s auto-stub logic
(`gimple_codegen.py` ~line 12262) has two branches for "this method
isn't known anywhere in this TU" — a real `__attribute__((weak))`
definition for structs in `_structs_with_unresolved_base` (safe: prints
a runtime warning if actually called), vs. a bare forward
DECLARATION for the ordinary "sibling method not yet emitted, will be
defined later in this same TU" case. Because `TimedRotatingFileHandler`/
`RotatingFileHandler` weren't in the set, calls like
`self.handleError(record)` got the bare-declaration branch — which is
correct for a same-struct forward reference but leaves a genuine
undefined symbol at link time when (as here) no such definition ever
actually gets emitted anywhere in the program.

`self.namer(...)`/`self.rotator(...)` hit the exact same branch for a
related but distinct reason: `namer`/`rotator` are plain `= None`
class-level DATA attributes (never a `def`), conditionally reassigned by
calling code to a callable and invoked through `if callable(self.namer):
... self.namer(...)`. The auto-stub path doesn't distinguish "real
method never defined" from "this "call" is actually a data-attribute
access" — both fall through the same no-known-declaration branch, and
both are fixed by the same widening (once the struct is correctly
flagged, the safe weak-stub definition covers this shape too, since a
real fix for "call through a possibly-None attribute" is a separate,
larger feature not attempted here).

### Fix

`gen_module`'s `_structs_with_unresolved_base` computation
(`gimple_codegen.py`, right before `_merge_struct_inheritance`) is now a
transitive closure over the base-class chain instead of a direct-base-
only check: a struct is included if ANY base in its chain (however many
levels up, following only bases that are themselves known `StructDef`s)
is unresolved, memoized with a cycle guard. This is a narrow, self-
contained change — the set is consumed at exactly one call site
(the auto-stub branch decision) — not a change to method resolution,
struct merging, or any other shared codegen path.

Verified: `TimedRotatingFileHandler`/`RotatingFileHandler` now both
appear in `_structs_with_unresolved_base` (confirmed via direct
`GimpleGen` introspection), and `python3 mojo.py build
.../Lib/logging/handlers.py` now builds cleanly (`Built: .../handlers`,
exit 0, no `error:`/undefined-symbol output). `Lib/logging/config.py`
(which imports `handlers.py` — see `bugs/COMPILE_FAIL_logging_config.md`)
now builds cleanly too, as a direct consequence.

### Quality gate (2026-08-07)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean (`Results: 1 passed, 0 failed`, "✓
   self-host compiles + links clean").
4. From-scratch stdlib dylib rebuild (`rm -f build/libmojostdlib.dylib`
   + `build_stdlib_dylib.build_stdlib(jobs=8)`) — clean, 0 `skip
   <module>:` lines.
5. `python3 compile_stdlib.py -j8` — **664/664 passed, 0 unexpected
   failures**.
6. Cross-cutting spot-check (this fix touches shared struct-inheritance
   machinery used by every class-hierarchy compile): `Lib/json/__init__.py`
   builds clean (unchanged). `Lib/tkinter/filedialog.py` and
   `Lib/tkinter/simpledialog.py` (previously failing on an UNRELATED
   same-bare-name struct collision, `bugs/hard/
   CODEGEN_same_bare_name_struct_collision_across_modules.md`, task
   #141 — explicitly out of scope this session) now also build clean in
   this environment, but NOT because of this fix or #141 being resolved
   — `MOJO_DEBUG=1` shows `tkinter.dialog`/`tkinter.simpledialog` fail
   to resolve as importable submodules at all here ("Only stdlib and
   test imports supported"), so the colliding `Dialog` classes never
   both enter the same transitive closure in this build path. Documented
   in `bugs/COMPILE_FAIL_tkinter_filedialog.md`/
   `bugs/COMPILE_FAIL_tkinter_simpledialog.md`; #141 remains genuinely
   unfixed and could still resurface under different import-resolution
   conditions.

## Status (updated 2026-08-06, historical — superseded)

Re-ran; current error:

```
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:1130:1: error: invalid conversion in gimple call
```

Line 1130 is a docstring line, not executable code — same line-number
misattribution pattern seen elsewhere this session (generated code
continuing past the last real `#line` directive without resetting it).
Not root-caused further given the imprecise location; `bugs/COMPILE_FAIL_importlib__bootstrap_external.md`'s
own still-open "invalid conversion in gimple call" sites (an
if/else-branched `with` block returning from structurally different
context-manager types) are a plausible same-shape candidate worth
checking first in any follow-up, given the identical error text. Not
fixed here.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:431:11: warning: unused variable '_tag' [-Wunused-variable]
  431 |         """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:436:11: warning: unused variable '_tag' [-Wunused-variable]
  436 |             timeTuple = time.gmtime(t)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:441:11: warning: unused variable '_tag' [-Wunused-variable]
  441 |             if dstNow != dstThen:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:456:11: warning: unused variable '_tag' [-Wunused-variable]
  456 |         self.rotate(self.baseFilename, dfn)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:465:13: warning: unused variable '_tag' [-Wunused-variable]
  465 |     """
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py: In function 'BaseRotatingHandler___init__':
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:782:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  782 |     LOG_KERN      = 0       #  kernel messages
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:780:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  780 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:779:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  779 |     LOG_DEBUG     = 7       #  debug-level messages
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:778:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  778 |     LOG_INFO      = 6       #  informational
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:777:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  777 |     LOG_NOTICE    = 5       #  normal but significant condition
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:776:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  776 |     LOG_WARNING   = 4       #  warning conditions
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:775:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  775 |     LOG_ERR       = 3       #  error conditions
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:774:25: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  774 |     LOG_CRIT      = 2       #  critical conditions
      |                         ^~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:773:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  773 |     LOG_ALERT     = 1       #  action must be taken immediately
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/logging/handlers.py:772:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
... (8687 more lines)
```

Exit code: 1
Elapsed: 10.37s
