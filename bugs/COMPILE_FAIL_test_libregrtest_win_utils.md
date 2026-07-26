# COMPILE_FAIL: Lib/test/libregrtest/win_utils.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:47:11: warning: unused variable '_tag' [-Wunused-variable]
   47 |         while _wait(self._running, 1000):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 |     def _calculate_load(self,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:57:11: warning: unused variable '_tag' [-Wunused-variable]
   57 |         # get the 'System' object
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |         #   DWORD HeaderLength
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:81:13: warning: unused variable '_tag' [-Wunused-variable]
   81 |             #   DWORD ByteLength
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py: In function 'WindowsLoadTracker___init__':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:40:14: error: 'WindowsLoadTracker' has no member named '_update_load'
   40 |         _thread.start_new_thread(self._update_load, (), {})
      |              ^~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:174:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:172:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:171:14: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:170:14: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:169:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:168:10: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:167:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:166:24: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:165:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:164:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:163:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:162:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:161:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:160:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:159:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:158:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:157:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:156:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:155:14: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:154:14: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:153:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:152:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:151:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:150:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/win_utils.py:149:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
... (426 more lines)
```

Exit code: 1
Elapsed: 10.14s
