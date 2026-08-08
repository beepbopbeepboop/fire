# COMPILE_FAIL: Modules/getpath.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/getpath.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-07, Track A continuation session)

The chained-assignment root cause below is now FIXED (see
`bugs/hard/CODEGEN_multi_assign_local_var_type_not_inferred.md`) — both
`Modules/getpath.py`'s own chained-assignment sites now get their
correct `char *` type at the point they're assigned. The file STILL
does not compile clean, for two SEPARATE, NOT-fixed reasons:

1. A newly-found, genuinely DISTINCT bug specific to `_gen_toplevel`
   (module-level/script-style top-level code, as opposed to an ordinary
   `def`'s body) — see "NEW, DISTINCT finding" below. Still produces
   the identical `error: assignment to 'int64_t' from 'char *'` symptom
   at `executable_dir`'s OTHER (non-chained) reassignment sites, e.g.
   line 449.
2. The `search_up` argument-type errors (line 580/595/628) — confirmed
   to be the EXCLUDED `*args`-spread-call category, see below. Not
   attempted (task #142, explicitly on this session's "do not touch"
   list).

### NEW, DISTINCT finding: `_gen_toplevel` has no whole-body type pre-pass, so a variable's FIRST assignment (even to an unresolved-stub's `int64_t` return) permanently locks its declared C type

```
error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
```
still occurs at line 449 (`executable_dir = real_executable_dir =
dirname(real_executable)` — itself a chained assignment, now correctly
computing `char *` for its RHS) even after the chained-assignment fix,
because `executable_dir`'s type was already locked to `int64_t` by an
EARLIER, ordinary (non-chained) assignment reached first during
codegen: line 298, `executable_dir = abspath('.')`. `abspath` is not a
name this compiler can resolve (it's one of many names CPython's real
`getpath.c` injects into `getpath.py`'s exec() namespace at C-embedding
time — `abspath`/`isfile`/`warn`/etc. are all unresolvable here), so it
compiles as a `__attribute__((weak)) int64_t abspath(...)` stub
(confirmed in the generated `.ci`), and `executable_dir`'s first-ever
`_declare_var` call (inside `_gen_toplevel`, which — unlike an ordinary
`def`'s body — is generated as one direct top-to-bottom pass with NO
`_infer_local_var_types`-style pre-scan unifying every assignment's
type ahead of time) locks in that stub's `int64_t` return type
permanently. Every LATER real-string reassignment to `executable_dir`
(including the now-correctly-`char *`-typed chained assignments) then
hits the same "assignment to int64_t from char *" GIMPLE error, just
downstream of a different root cause than the one this doc originally
diagnosed. Not fixed here — this is a substantial, high-risk, separate
fix (giving `_gen_toplevel` its own whole-body type-unification
pre-pass, mirroring `_infer_local_var_types`, across literally every
compiled module's top-level code, which is an extremely hot path).
Worth a dedicated hard-bug doc if picked up in a future session.

### `search_up` argument-type errors: confirmed EXCLUDED category, not attempted

```python
def search_up(prefix, *landmarks, test=isfile):
    ...
prefix = search_up(library_dir, ZIP_LANDMARK)   # line 580, single landmark
```
`search_up`'s compiled signature packs its `*landmarks` varargs
parameter into a `MojoList *`; GCC's error ("expected 'MojoList *' but
argument is of type 'char *'") is call sites passing a single bare
positional value (`ZIP_LANDMARK`, a `char *`) for a `*args`-spread
parameter without it having been collected into a list first — this is
exactly the shape of `bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.md`
(task #142), explicitly excluded from this session. Confirmed, not
attempted.

### Original root-cause writeup (2026-08-06, chained-assignment half — now fixed)

Root-caused the first (and most common) group: every one is a chained/
multi-target assignment —
```python
executable_dir = real_executable_dir = value.strip()
...
prefix = exec_prefix = ''
```
`_infer_local_var_types` (`gimple_codegen.py`), the pre-pass that
determines a local variable's real declared C type, had NO case for
`MultiAssignStmt` (`a = b = expr`) at all — only plain single-target
`AssignStmt`. Every target of a chained assignment was invisible to it
and fell through to the generic `int64_t` default. FIXED, see
`bugs/hard/CODEGEN_multi_assign_local_var_type_not_inferred.md`.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Modules/getpath.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Modules/getpath.py:137:11: warning: unused variable '_tag' [-Wunused-variable]
  137 | # Step 4. If 'home' is set, either by Py_SetHome(), ENV_PYTHONHOME,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/getpath.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Modules/getpath.py:142:11: warning: unused variable '_tag' [-Wunused-variable]
  142 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Modules/getpath.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Modules/getpath.py:147:11: warning: unused variable '_tag' [-Wunused-variable]
  147 | # subdirectory of prefix, both will be found.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/getpath.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Modules/getpath.py:162:11: warning: unused variable '_tag' [-Wunused-variable]
  162 | # installation location, even though sys.path points into the build
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/getpath.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Modules/getpath.py:171:13: warning: unused variable '_tag' [-Wunused-variable]
  171 | # ******************************************************************************
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Modules/getpath.py: In function 'search_up':
/Users/mrs/net/Python-3.14.6/Modules/getpath.py:289:11: warning: variable 'f' set but not used [-Wunused-but-set-variable]
  289 |         if isxfile(p):
      |           ^
/Users/mrs/net/Python-3.14.6/Modules/getpath.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Modules/getpath.py:580:35: error: passing argument 2 of 'search_up' from incompatible pointer type [-Wincompatible-pointer-types]
  580 |                 prefix = search_up(library_dir, ZIP_LANDMARK)
      |                                   ^~~~~~~~~~~~
      |                                   |
      |                                   char *
/Users/mrs/net/Python-3.14.6/Modules/getpath.py:284:47: note: expected 'MojoList *' but argument is of type 'char *'
  284 |     # Resolve names against PATH.
      |                                               ^        
/Users/mrs/net/Python-3.14.6/Modules/getpath.py:595:38: error: passing argument 2 of 'search_up' from incompatible pointer type [-Wincompatible-pointer-types]
  595 |             prefix = search_up(executable_dir, ZIP_LANDMARK)
      |                                      ^~~~~~~~~~~~
      |                                      |
      |                                      char *
/Users/mrs/net/Python-3.14.6/Modules/getpath.py:284:47: note: expected 'MojoList *' but argument is of type 'char *'
  284 |     # Resolve names against PATH.
      |                                               ^        
/Users/mrs/net/Python-3.14.6/Modules/getpath.py:628:39: error: passing argument 2 of 'search_up' from incompatible pointer type [-Wincompatible-pointer-types]
  628 |             exec_prefix = search_up(executable_dir, PLATSTDLIB_LANDMARK, test=isdir)
      |                                       ^~~~~~~~~~~~~~~~~~~
      |                                       |
      |                                       char *
/Users/mrs/net/Python-3.14.6/Modules/getpath.py:284:47: note: expected 'MojoList *' but argument is of type 'char *'
  284 |     # Resolve names against PATH.
      |                                               ^        
... (116 more lines)
```

Exit code: 1
Elapsed: 13.32s
