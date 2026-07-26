# COMPILE_FAIL: Lib/idlelib/history.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:27:11: warning: unused variable '_tag' [-Wunused-variable]
   27 |         self.cyclic = idleConf.GetOption("main", "History", "cyclic", 1, "bool")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:32:11: warning: unused variable '_tag' [-Wunused-variable]
   32 |         "Fetch later statement; start with earliest if cyclic."
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:37:11: warning: unused variable '_tag' [-Wunused-variable]
   37 |         "Fetch earlier statement; start with most recent."
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 |         if pointer is not None and prefix is not None:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:61:13: warning: unused variable '_tag' [-Wunused-variable]
   61 |             else:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py: In function 'History___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:178:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:176:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:175:7: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:174:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:173:10: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:172:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:171:10: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:170:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:169:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:168:7: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:167:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:166:10: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:165:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:164:10: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:163:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:162:7: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:161:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:160:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:159:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:158:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:157:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:156:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:155:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:154:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:153:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:152:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:151:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/history.py:150:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
... (566 more lines)
```

Exit code: 1
Elapsed: 11.84s
