# COMPILE_FAIL: Lib/operator.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/operator.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:156:11: warning: unused variable '_tag' [-Wunused-variable]
  156 |     if not hasattr(a, '__getitem__'):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:161:11: warning: unused variable '_tag' [-Wunused-variable]
  161 | def contains(a, b):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:166:11: warning: unused variable '_tag' [-Wunused-variable]
  166 |     "Return the number of items in a which are, or which equal, b."
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:181:11: warning: unused variable '_tag' [-Wunused-variable]
  181 | def indexOf(a, b):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:190:13: warning: unused variable '_tag' [-Wunused-variable]
  190 |     "Same as a[b] = c."
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function 'lt_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:598:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function 'le_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:34:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   34 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function 'eq_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:38:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   38 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function 'ne_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:42:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   42 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function 'ge_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:46:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   46 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function 'gt_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:50:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   50 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function 'not__0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:54:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   54 |     "Same as not a."
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/operator.py: In function 'truth_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/operator.py:60:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   60 | 
... (705 more lines)
```

Exit code: 1
Elapsed: 9.65s
