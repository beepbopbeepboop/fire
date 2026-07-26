# COMPILE_FAIL: Tools/c-analyzer/c_parser/parser/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:29:11: warning: unused variable '_tag' [-Wunused-variable]
   29 |    + (stmt) continue:  at end
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:34:11: warning: unused variable '_tag' [-Wunused-variable]
   34 |    + (decl) param-list:  between params
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:39:11: warning: unused variable '_tag' [-Wunused-variable]
   39 | * ":"
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 |    + (expr) postfix (func call):  around args
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:63:13: warning: unused variable '_tag' [-Wunused-variable]
   63 |    + (decl) func:  around body
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function 'parse_a64463':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:157:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  157 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function '_alloc_anonymous_names_anon_name_env':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:139:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  139 |         nonlocal counter
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py: In function 'anonymous_names_anon_name':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:164:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  164 | # We use defaults that cover most files.  Files with bigger declarations
      | ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:162:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  162 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:161:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  161 |         yield result
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:160:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  160 |         # XXX Handle blocks here instead of in parse_globals().
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:159:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  159 |     for result in parse_globals(source, anon_name):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:158:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  158 |     source = _iter_source(srclines, **srckwargs)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py:157:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  157 | 
... (91 more lines)
```

Exit code: 1
Elapsed: 13.31s
