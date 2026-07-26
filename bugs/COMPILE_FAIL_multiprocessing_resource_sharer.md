# COMPILE_FAIL: Lib/multiprocessing/resource_sharer.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py: In function '_alloc__ResourceSharer':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:52:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   52 |                 os.close(new_fd)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py: In function '_ResourceSharer___init__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:253:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:251:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:250:7: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:249:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:248:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:247:21: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:246:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:245:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:244:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:243:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:242:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:241:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:240:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:239:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:238:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:237:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:236:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py: In function '_ResourceSharer_mojo_register':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:99:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   99 |                 self._thread.join(timeout)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:82:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   82 |     def get_connection(ident):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:77:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   77 |             self._key += 1
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:75:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   75 |             if self._address is None:
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py: In function '_ResourceSharer_get_connection':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:111:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  111 |     def _afterfork(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:109:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  109 |                 self._cache.clear()
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:108:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  108 |                     close()
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:107:10: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  107 |                 for key, (send, close) in self._cache.items():
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_sharer.py:106:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
... (701 more lines)
```

Exit code: 1
Elapsed: 9.83s
