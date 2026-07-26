# COMPILE_FAIL: Lib/multiprocessing/dummy/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |     return list(children)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:78:11: warning: unused variable '_tag' [-Wunused-variable]
   78 | #
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:83:11: warning: unused variable '_tag' [-Wunused-variable]
   83 |     def __init__(self, /, **kwds):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:98:11: warning: unused variable '_tag' [-Wunused-variable]
   98 |     return array.array(typecode, sequence)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:107:13: warning: unused variable '_tag' [-Wunused-variable]
  107 |         return self._value
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py: In function 'DummyProcess___init__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:240:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:238:7: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:237:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:236:9: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:235:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:234:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:233:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:232:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:231:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:230:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:229:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:228:18: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:227:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:226:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:225:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:224:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:223:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py: In function 'DummyProcess_start':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:53:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   53 |     @property
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:57:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   57 |         else:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:91:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   91 |         temp.sort()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/dummy/__init__.py:86:1: warning: label 'bb_3' defined but not used [-Wunused-label]
... (261 more lines)
```

Exit code: 1
Elapsed: 9.88s
