# COMPILE_FAIL: Lib/unittest/_log.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py: In function '_alloc__CapturingHandler':
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:72:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   72 |         if self.no_logs:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py: In function '_CapturingHandler___init__':
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:237:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:235:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:234:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:233:14: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:232:14: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:231:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:230:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:229:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:228:23: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:227:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:226:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:225:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:224:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:223:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py: In function '_CapturingHandler_flush':
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:23:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   23 |         self.watcher.records.append(record)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py: In function '_CapturingHandler_emit':
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:44:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   44 |         if isinstance(self.logger_name, logging.Logger):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:42:7: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
   42 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:41:14: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
   41 |         self.no_logs = no_logs
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:40:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
   40 |         self.msg = None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:39:10: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   39 |             self.level = logging.INFO
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:38:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   38 |         else:
      |           ^~~ 
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:37:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   37 |             self.level = logging._nameToLevel.get(level, level)
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:36:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   36 |         if level:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/_log.py:35:7: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
... (468 more lines)
```

Exit code: 1
Elapsed: 14.12s
