# COMPILE_FAIL: Lib/multiprocessing/context.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py: In function '_alloc_DefaultContext':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:100:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  100 |     def Queue(self, maxsize=0):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py: In function 'BaseContext_cpu_count':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:50:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   50 |         '''Returns a manager associated with a running server process
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:57:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   57 |         m.start()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:49:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   49 |     def Manager(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:365:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  365 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:363:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  363 | def _force_start_method(method):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:362:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  362 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:361:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  361 | #
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:360:9: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  360 | # Force the start method
      |         ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:359:11: warning: variable 'num' set but not used [-Wunused-but-set-variable]
  359 | #
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:358:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  358 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:357:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  357 |     _default_context = DefaultContext(_concrete_contexts['spawn'])
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:356:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  356 |     }
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py: In function 'BaseContext_Manager':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:63:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   63 |         return Pipe(duplex)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:61:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   61 |         '''Returns two connection object connected by a pipe'''
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/context.py:60:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
... (1627 more lines)
```

Exit code: 1
Elapsed: 9.95s
