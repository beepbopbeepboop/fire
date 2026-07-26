# COMPILE_FAIL: Tools/build/smelly.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:39:11: warning: unused variable '_tag' [-Wunused-variable]
   39 |     # and "_edata (type: D)".
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:44:11: warning: unused variable '_tag' [-Wunused-variable]
   44 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:49:11: warning: unused variable '_tag' [-Wunused-variable]
   49 |     # Only look at dynamic symbols
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:64:11: warning: unused variable '_tag' [-Wunused-variable]
   64 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:73:13: warning: unused variable '_tag' [-Wunused-variable]
   73 |         if not line:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py: In function 'is_local_symbol_type_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:202:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:194:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py: In function 'get_exported_symbols_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:94:11: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
   94 |         else:
      |           ^~~ 
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:90:11: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
   90 |         if is_local_symbol_type(symtype):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:88:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
   88 |             continue
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:63:7: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   63 |     return stdout
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:62:7: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   62 |         raise Exception("command output is empty")
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py: In function 'get_smelly_symbols_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:75:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   75 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py: In function 'check_library_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:129:7: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
  129 |             pybuilddir = fp.readline()
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py: In function 'check_extensions':
/Users/mrs/net/Python-3.14.6/Tools/build/smelly.py:174:11: warning: variable '_t47' set but not used [-Wunused-but-set-variable]
... (101 more lines)
```

Exit code: 1
Elapsed: 13.56s
