# COMPILE_FAIL: Lib/multiprocessing/sharedctypes.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py: In function '_alloc_Synchronized':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:85:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   85 |     '''
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py: In function '_alloc_SynchronizedArray':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:99:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   99 |     new_obj = _new_value(type(obj))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py: In function '_alloc_SynchronizedString':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:113:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  113 |     else:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:380:54: error: 'synchronized_132aaf' undeclared here (not in a function); did you mean 'SynchronizedBase'?
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py: In function '_new_value_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:441:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:437:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py: In function 'RawValue':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:69:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   69 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:65:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
   65 |         type_ = type_ * len(size_or_initializer)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:63:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   63 |         return obj
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:62:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   62 |         ctypes.memset(ctypes.addressof(obj), 0, ctypes.sizeof(obj))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:61:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   61 |         obj = _new_value(type_)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:59:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   59 |     if isinstance(size_or_initializer, int):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:58:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   58 |     type_ = typecode_to_type.get(typecode_or_type, typecode_or_type)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:47:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   47 |     '''
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py: In function 'RawArray_d01dc0':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:92:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
   92 |         ctx = ctx or get_context()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/sharedctypes.py:90:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
   90 |         return obj
      |           ^~~~
... (937 more lines)
```

Exit code: 1
Elapsed: 9.70s
