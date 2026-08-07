# COMPILE_FAIL: Mac/BuildScript/build-installer.py

Source file: `/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current errors, two distinct root causes:

```
error: invalid operands to binary + (have 'char *' and 'MojoList *')
error: invalid operands to binary % (have 'int64_t' and 'MojoDict *')  (x2)
```

1. `FW_VERSION_PREFIX = "--undefined--"` at module scope (a STRING
   placeholder, "initialized in parseOptions" per its own comment),
   later reassigned inside a function to a real LIST value:
   `FW_VERSION_PREFIX = FW_PREFIX[:] + ["Versions", getVersion()]`.
   `gen_module`'s Phase 1.7 global prescan types a global from
   whichever assignment it encounters (here: the module-level
   `StringLiteral` → `char *`), with no reconciliation for a LATER
   reassignment to a structurally different type inside a function —
   a placeholder-then-real-type-reassignment idiom, related to (but a
   distinct trigger shape from) `bugs/hard/CODEGEN_global_prescan_blind_to_trystmt_and_bare_annotation.md`
   and `bugs/hard/CODEGEN_reset_func_wipes_global_container_type_inference.md`
   (both already document other Phase-1.7-adjacent global-typing gaps
   found this session).

2. `readme = readme % textvars` / `srcdir = srcdir % textvars` — old-
   style `"..." % {dict}` string formatting where the LHS `readme`/
   `srcdir` (both function parameters, presumably `str`) resolve to
   `int64_t` instead of `char *`, and `%` against a `MojoDict *` RHS
   isn't specially handled at all (the `%` operator lowering likely
   only recognizes tuple-style `%` formatting, not dict-style). Not
   investigated further.

Neither fixed here.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:85:11: warning: unused variable '_tag' [-Wunused-variable]
   85 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:90:11: warning: unused variable '_tag' [-Wunused-variable]
   90 |     if _cache_getVersion is None:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:95:11: warning: unused variable '_tag' [-Wunused-variable]
   95 | def getVersionMajorMinor():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:110:11: warning: unused variable '_tag' [-Wunused-variable]
  110 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:119:13: warning: unused variable '_tag' [-Wunused-variable]
  119 | # else if you don't want to re-fetch required libraries every time.
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function 'shellQuote_0c85c9':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:694:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  694 |         else:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:692:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  692 |                 raise NotImplementedError(v)
      |          ^  
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:688:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  688 |                     # Select alternate default deployment
      |          ^  
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function 'grepValue_d01dc0':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:88:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   88 | def getVersion():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:76:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   76 |     QUOTED_VALUE='quotes'    -> str('quotes')
      |          ^~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function 'getFullVersion':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:112:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  112 | FW_VERSION_PREFIX = "--undefined--" # initialized in parseOptions
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function 'tweak_tcl_build_1ce6ce':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:280:11: warning: variable '_t62' set but not used [-Wunused-but-set-variable]
  280 |               buildDir="unix",
      |           ^   
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:276:11: warning: variable '_t58' set but not used [-Wunused-but-set-variable]
  276 |           dict(
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:268:7: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
... (1375 more lines)
```

Exit code: 1
Elapsed: 13.33s
