# COMPILE_FAIL: CC ERROR: invalid use of void expression

**2 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:84:11: warning: unused variable '_tag' [-Wunused-variable]
   84 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:89:11: warning: unused variable '_tag' [-Wunused-variable]
   89 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:94:11: warning: unused variable '_tag' [-Wunused-variable]
   94 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:109:11: warning: unused variable '_tag' [-Wunused-variable]
  109 |     # annotations
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:118:13: warning: unused variable '_tag' [-Wunused-variable]
  118 |     kwargs['e'] = e
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py: In function 'complex_script_spam_minimal':
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:10:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   10 |         pass
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py: In function 'complex_script':
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:14:11: warning: format '%d' expects argument of type 'int', but argument 2 has type 'MojoList *' [-Wformat=]
   14 |     assert res == obj, (res, obj)
      |           ^~~~~~  ~~~~
      |                   |
      |                   MojoList *
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:27:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   27 | def script_with_return():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:20:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   20 |     assert obj2 is None
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:16:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   16 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py: In function 'spam_with_builtins':
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:45:11: warning: variable 'x' set but not used [-Wunused-but-set-variable]
   45 |     values = (42,)
      |           ^
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py: In function 'spam_with_global_and_attr_same_name':
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:62:7: error: invalid use of void expression
   62 |         spam_minimal.spam_minimal
      |       ^
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:70:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   70 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:67:10: warning: unused variable '_t6' [-Wunused-variable]
   67 | def spam_full_args(a, b, /, c, d, *args, e, f, **kwargs):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py: In function 'spam_with_inner_not_closure_eggs':
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:99:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   99 |         print(x)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py: In function '_alloc_spam_with_inner_closure_eggs_env':
/Users/mrs/net/Python-3.14.6/Lib/test/_code_definitions.py:101:1: warning: label 'bb_2' defined but not used [-Wunused-label
```

## Affected files

- `Lib/test/_code_definitions.py`
- `Lib/test/crashers/bogus_code_obj.py`
