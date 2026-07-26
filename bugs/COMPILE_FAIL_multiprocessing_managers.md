# COMPILE_FAIL: Lib/multiprocessing/managers.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py: In function '_alloc_ProcessLocalSet':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:634:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  634 |             conn.close()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py: In function '_alloc_RemoteError':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:648:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  648 |             self.start()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py: In function '_alloc_Server':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:662:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  662 |     @staticmethod
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py: In function '_alloc_State':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:676:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  676 |             except Exception:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py: In function '_alloc_Token':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:690:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  690 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:1198:57: error: 'IteratorProxy_close' undeclared here (not in a function); did you mean 'IteratorProxy_mojo_close'?
 1198 | collections.abc.MutableMapping.register(_BaseDictProxy)
      |                                                         ^                  
      |                                                         IteratorProxy_mojo_close
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:1267:45: error: 'BarrierProxy_abort' undeclared here (not in a function); did you mean 'BarrierProxy_reset'?
 1267 | SyncManager.register('Queue', queue.Queue)
      |                                             ^                 
      |                                             BarrierProxy_reset
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py: In function 'Token___init__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:60:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   60 | # Type for identifying shared objects
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py: In function 'Token___getstate__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:81:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   81 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py: In function 'Token___setstate__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:88:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   88 |     Send a message to manager using connection `c` and return response
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:86:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   86 | def dispatch(c, id, methodname, args=(), kwds={}):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:85:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   85 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/managers.py:84:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   84 | #
... (20748 more lines)
```

Exit code: 1
Elapsed: 10.42s
