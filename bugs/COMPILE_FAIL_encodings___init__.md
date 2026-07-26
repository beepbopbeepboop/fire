# COMPILE_FAIL: Lib/encodings/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:44:11: warning: unused variable '_tag' [-Wunused-variable]
   44 | def normalize_encoding(encoding):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:49:11: warning: unused variable '_tag' [-Wunused-variable]
   49 |         characters except the dot used for Python package names are
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:69:11: warning: unused variable '_tag' [-Wunused-variable]
   69 |             punct = True
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:78:13: warning: unused variable '_tag' [-Wunused-variable]
   78 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py: In function 'normalize_encoding_fa7153':
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:57:9: error: too many arguments to function 'mojo_str'; expected 1, have 2
   57 |         encoding = str(encoding, "ascii")
      |         ^~~~~~~~        ~~~
In file included from __init__.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:312:7: note: declared here
  312 | char *mojo_str(void *obj);  /* Flexible signature for both int and char* */
      |       ^~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:175:9: warning: variable 'punct' set but not used [-Wunused-but-set-variable]
  175 |         try:
      |         ^~~~ 
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:160:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  160 | # Register the search_function in the Python codec registry
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py: In function 'search_function_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:367:11: warning: variable 'codecaliases' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:364:10: warning: unused variable '_t283' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:352:7: warning: variable '_t271' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:341:11: warning: variable '_t260' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:329:10: warning: variable '_t248' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:181:7: warning: variable '_t100' set but not used [-Wunused-but-set-variable]
  181 | 
      |       ^    
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:158:10: warning: unused variable '_t78' [-Wunused-variable]
  158 |     return entry
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/__init__.py:142:10: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
  142 |     if len(_cache) >= _MAXCACHE:
      |          ^~~~
... (63 more lines)
```

Exit code: 1
Elapsed: 9.77s
