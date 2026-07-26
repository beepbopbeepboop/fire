# COMPILE_FAIL: Tools/c-analyzer/cpython/_capi.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: warning: f-string interpolation '{extra+"}' could not be compiled; emitting it as literal text (SyntaxError: 1:0: Unexpected NEWLINE(''))
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: warning: f-string interpolation '{outer + "}' could not be compiled; emitting it as literal text (SyntaxError: 1:0: Unexpected NEWLINE(''))
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: warning: f-string interpolation '{outer + "}' could not be compiled; emitting it as literal text (SyntaxError: 1:0: Unexpected NEWLINE(''))
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: warning: f-string interpolation '{inner + "}' could not be compiled; emitting it as literal text (SyntaxError: 1:0: Unexpected NEWLINE(''))
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: warning: f-string interpolation '{extra+"}' could not be compiled; emitting it as literal text (SyntaxError: 1:0: Unexpected NEWLINE(''))
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: warning: f-string interpolation '{outer + "}' could not be compiled; emitting it as literal text (SyntaxError: 1:0: Unexpected NEWLINE(''))
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: warning: f-string interpolation '{outer + "}' could not be compiled; emitting it as literal text (SyntaxError: 1:0: Unexpected NEWLINE(''))
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: warning: f-string interpolation '{inner + "}' could not be compiled; emitting it as literal text (SyntaxError: 1:0: Unexpected NEWLINE(''))
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py:100:11: warning: unused variable '_tag' [-Wunused-variable]
  100 |         {_ind(CAPI_DEFINE, 2)}
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py:105:11: warning: unused variable '_tag' [-Wunused-variable]
  105 |     'func',
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py:110:11: warning: unused variable '_tag' [-Wunused-variable]
  110 | ]
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py:125:11: warning: unused variable '_tag' [-Wunused-variable]
  125 |         return None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py:134:13: warning: unused variable '_tag' [-Wunused-variable]
  134 |                 if not clean.endswith('\\'):
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: In function '_parse_line_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py:408:11: warning: variable 'results' set but not used [-Wunused-but-set-variable]
  408 |         'kind': maxkind,
      |           ^~~~~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py:391:10: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
  391 |     collated = {}
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py:380:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
  380 |                 raw = raw.strip()
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py:363:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  363 |                 try:
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py:355:11: warning: variable 'last' set but not used [-Wunused-but-set-variable]
  355 |     if isinstance(ignored, str):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: In function '_get_level_7a6366':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py:166:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  166 |     elif os.path.dirname(filename) == INCLUDE_ROOT:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/_capi.py: In function 'CAPIItem_from_line':
... (521 more lines)
```

Exit code: 1
Elapsed: 13.86s
