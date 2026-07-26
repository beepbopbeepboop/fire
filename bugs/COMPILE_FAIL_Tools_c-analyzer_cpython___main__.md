# COMPILE_FAIL: Tools/c-analyzer/cpython/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:94:11: warning: unused variable '_tag' [-Wunused-variable]
   94 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:99:11: warning: unused variable '_tag' [-Wunused-variable]
   99 |     yield '===================='
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:104:11: warning: unused variable '_tag' [-Wunused-variable]
  104 |     yield from section('variables', unsupported)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:119:11: warning: unused variable '_tag' [-Wunused-variable]
  119 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:128:13: warning: unused variable '_tag' [-Wunused-variable]
  128 |         get_preprocessor=_parser.get_preprocessor,
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py: In function '_alloc_fmt_summary_section_env':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:74:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   74 |     supported = []
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py: In function 'fmt_summary_section':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:103:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  103 |     yield from section('types', unsupported)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:101:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  101 |     yield '===================='
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:100:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  100 |     yield 'unsupported'
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:99:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
   99 |     yield '===================='
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:98:14: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   98 |     yield ''
      |              ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:97:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   97 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:96:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   96 |     yield from section('variables', supported)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/cpython/__main__.py:95:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   95 |     yield from section('types', supported)
      |           ^~~~
... (1559 more lines)
```

Exit code: 1
Elapsed: 14.34s
