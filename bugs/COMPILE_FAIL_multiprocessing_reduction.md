# COMPILE_FAIL: Lib/multiprocessing/reduction.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py: In function '_alloc_ForkingPickler':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:84:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   84 |         '''Steal a handle from process identified by source_pid.'''
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py: In function '_alloc__C':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:98:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   98 |         conn.send(dh)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py: In function 'ForkingPickler___init__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:303:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:301:7: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:300:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:299:14: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:298:7: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:297:14: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:296:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:295:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:294:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:293:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:292:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:291:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:290:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:289:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:288:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:287:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py: In function 'ForkingPickler_mojo_register':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:56:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   56 | register = ForkingPickler.register
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:54:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   54 |     loads = pickle.loads
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:53:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   53 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:52:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   52 |         return buf.getbuffer()
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:51:14: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   51 |         cls(buf, protocol).dump(obj)
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:50:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   50 |         buf = io.BytesIO()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:49:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   49 |     def dumps(cls, obj, protocol=None):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/reduction.py:48:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   48 |     @classmethod
... (202 more lines)
```

Exit code: 1
Elapsed: 9.72s
