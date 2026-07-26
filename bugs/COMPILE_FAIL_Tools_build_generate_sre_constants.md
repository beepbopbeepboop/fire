# COMPILE_FAIL: Tools/build/generate_sre_constants.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:29:11: warning: unused variable '_tag' [-Wunused-variable]
   29 |  * See the sre.c file for information on usage and redistribution.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:34:11: warning: unused variable '_tag' [-Wunused-variable]
   34 | def main(
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:39:11: warning: unused variable '_tag' [-Wunused-variable]
   39 |     ns = {}
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:63:13: warning: unused variable '_tag' [-Wunused-variable]
   63 |     content.extend(dump(ns["ATCODES"], "SRE"))
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py: In function 'update_file_0335d0':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:182:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:156:10: warning: unused variable '_t6' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py: In function 'main_dump':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:50:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   50 |         items = [(value, name) for name, value in d.items()
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:56:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   56 |         for i, item in enumerate(sorted(d)):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:55:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   55 |     def dump_gotos(d, prefix):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:51:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   51 |                  if name.startswith(prefix)]
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:54:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   54 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:52:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   52 |         for value, name in sorted(items):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:51:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
   51 |                  if name.startswith(prefix)]
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:50:10: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
   50 |         items = [(value, name) for name, value in d.items()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sre_constants.py:49:10: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
... (353 more lines)
```

Exit code: 1
Elapsed: 13.94s
