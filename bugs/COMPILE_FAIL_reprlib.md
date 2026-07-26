# COMPILE_FAIL: Lib/reprlib.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/reprlib.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py: In function '_alloc_Repr':
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:86:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   86 |             module = getattr(cls, '__module__', None)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py: In function '_alloc_recursive_repr_decorating_function_wrapper_env':
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:357:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py: In function 'recursive_repr_decorating_function_wrapper':
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:33:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   33 |         wrapper.__wrapped__ = user_function
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:26:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   26 |         # Can't use functools.wraps() here because of bootstrap issues
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:23:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   23 |                 repr_running.discard(key)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:28:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   28 |         wrapper.__doc__ = getattr(user_function, '__doc__')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:30:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   30 |         wrapper.__qualname__ = getattr(user_function, '__qualname__')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:21:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   21 |                 result = user_function(self)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:25:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   25 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:397:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:395:7: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:394:10: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:393:14: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:392:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:391:13: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:390:11: warning: variable 'result' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:389:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:388:10: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:387:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:386:10: warning: unused variable '_t21' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:384:7: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:383:7: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:382:9: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:381:7: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:380:7: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:379:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:378:14: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:377:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:376:13: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/reprlib.py:375:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
... (605 more lines)
```

Exit code: 1
Elapsed: 11.68s
