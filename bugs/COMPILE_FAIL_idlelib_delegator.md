# COMPILE_FAIL: Lib/idlelib/delegator.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:26:11: warning: unused variable '_tag' [-Wunused-variable]
   26 |     def setdelegate(self, delegate):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:31:11: warning: unused variable '_tag' [-Wunused-variable]
   31 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:36:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:51:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:60:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py: In function 'Delegator___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:130:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:128:13: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:127:13: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:126:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py: In function 'Delegator___getattr__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:24:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   24 |         self.__cache.clear()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:22:7: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   22 |             except AttributeError:
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:21:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   21 |                 delattr(self, key)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:20:13: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   20 |             try:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:19:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   19 |         for key in self.__cache:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:18:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   18 |         # to original state.  Cache is just a means
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:17:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   17 |         # Function is really about resetting delegator dict
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:16:11: warning: variable 'attr' set but not used [-Wunused-but-set-variable]
   16 |         "Removes added attributes while leaving original attributes."
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:15:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   15 |     def resetcache(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/delegator.py:14:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   14 | 
... (137 more lines)
```

Exit code: 1
Elapsed: 11.54s
