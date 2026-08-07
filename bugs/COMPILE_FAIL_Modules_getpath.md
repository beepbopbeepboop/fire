# COMPILE_FAIL: Modules/getpath.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/getpath.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current errors:

```
error: assignment to 'int64_t' from 'char *' makes integer from pointer without a cast [-Wint-conversion]  (x6)
error: passing argument 2 of 'search_up' from incompatible pointer type [-Wincompatible-pointer-types]  (x2)
```

Root-caused the first (and most common) group: every one is a chained/
multi-target assignment —
```python
executable_dir = real_executable_dir = value.strip()
...
prefix = exec_prefix = ''
```
`_infer_local_var_types` (`gimple_codegen.py`), the pre-pass that
determines a local variable's real declared C type, has NO case for
`MultiAssignStmt` (`a = b = expr`) at all — only plain single-target
`AssignStmt`. Every target of a chained assignment is invisible to it
and falls through to the generic `int64_t` default. Written up as a
new hard bug:
`bugs/hard/CODEGEN_multi_assign_local_var_type_not_inferred.md` — this
one is cleaner/narrower than most of this session's other findings
(a single missing case in one well-contained function, not a multi-
mechanism interaction), but not fixed here given this session's general
caution about landing type-inference changes without dedicated
verification time.

The `search_up` argument-type errors (line 580/595) were not
investigated further.

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
