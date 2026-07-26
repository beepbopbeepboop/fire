# COMPILE_FAIL: Lib/test/test_tomllib/burntsushi.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:31:11: warning: unused variable '_tag' [-Wunused-variable]
   31 |     elif isinstance(obj, datetime.datetime):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:36:11: warning: unused variable '_tag' [-Wunused-variable]
   36 |     elif isinstance(obj, datetime.time):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 |     elif isinstance(obj, datetime.date):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
   56 |     This normalizes primitive values (e.g. floats), and also converts from
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:65:13: warning: unused variable '_tag' [-Wunused-variable]
   65 |         if "type" in obj and "value" in obj:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py: In function 'normalize_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:83:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   83 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:79:10: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
   79 |                 return [normalize(item) for item in value]
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:62:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   62 |     if isinstance(obj, list):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py: In function '_normalize_datetime_str_584a43':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:146:10: warning: variable '_t47' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:145:10: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:141:10: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:135:11: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:134:11: warning: variable '_' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:131:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:126:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:118:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  118 |         return "0"
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:113:10: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  113 | def _normalize_float_str(float_str: str) -> str:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py: In function '_normalize_localtime_str_584a43':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:116:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  116 |     # Normalize "-0.0" and "+0.0"
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tomllib/burntsushi.py:115:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
... (58 more lines)
```

Exit code: 1
Elapsed: 58.96s
