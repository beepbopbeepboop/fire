# COMPILE_FAIL: Lib/importlib/metadata/_adapters.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:69:11: warning: unused variable '_tag' [-Wunused-variable]
   69 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:74:11: warning: unused variable '_tag' [-Wunused-variable]
   74 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:79:11: warning: unused variable '_tag' [-Wunused-variable]
   79 |         per PEP 0566.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:94:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:103:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py: In function 'Message___new__':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:192:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:190:7: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:189:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:188:14: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:187:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:186:14: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:185:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:184:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:183:11: warning: variable 'res' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:182:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:181:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:180:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py: In function 'Message___init__':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:52:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   52 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:50:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   50 |     def __iter__(self):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:49:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   49 |     # suppress spurious error from mypy
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py: In function 'Message___iter__':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:55:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   55 |         Warn users that a ``KeyError`` can be expected when a
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:53:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   53 |     def __getitem__(self, item):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_adapters.py:52:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   52 | 
      |           ^  
... (258 more lines)
```

Exit code: 1
Elapsed: 10.33s
