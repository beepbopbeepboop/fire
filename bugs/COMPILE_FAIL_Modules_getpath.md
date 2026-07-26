# COMPILE_FAIL: Modules/getpath.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/getpath.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

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
