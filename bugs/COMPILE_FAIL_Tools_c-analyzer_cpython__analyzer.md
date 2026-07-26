# COMPILE_FAIL: Tools/c-analyzer/cpython/_analyzer.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:92:11: warning: unused variable '_tag' [-Wunused-variable]
   92 |     ('Modules/_lzmamodule.c', 'arg_names'),
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:97:11: warning: unused variable '_tag' [-Wunused-variable]
   97 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:102:11: warning: unused variable '_tag' [-Wunused-variable]
  102 |     if not _KNOWN:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:117:11: warning: unused variable '_tag' [-Wunused-variable]
  117 |     raise NotImplementedError
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:126:13: warning: unused variable '_tag' [-Wunused-variable]
  126 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py: In function 'read_known':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:350:7: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
  350 |     @classonly
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:343:11: warning: variable '_' set but not used [-Wunused-but-set-variable]
  343 |     elif is_funcptr(decl.vartype):
      |           ^
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:340:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  340 |         return None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:336:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  336 |                 unsupported = None
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:334:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  334 |             unsupported = extra.get('unsupported')
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:330:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  330 |             _, extra = found
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:329:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  329 |         if found is not None:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:327:11: warning: variable 'extracols' set but not used [-Wunused-but-set-variable]
  327 |             found = knowntypes.get(typedecl)
      |           ^ ~~~~~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py: In function 'write_known':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_analyzer.py:123:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  123 |         _IGNORED.update(_datafiles.read_ignored(IGNORED_FILE, relroot=REPO_ROOT))
      |           ^~~
... (671 more lines)
```

Exit code: 1
Elapsed: 13.90s
