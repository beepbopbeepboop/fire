# COMPILE_FAIL: Lib/importlib/_bootstrap.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py: In function '_alloc_ModuleSpec':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:156:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  156 | class _BlockingOnManager:
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py: In function '_alloc__BlockingOnManager':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:170:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  170 |         self.blocked_on = _blocking_on.setdefault(self.thread_id, _List())
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py: In function '_alloc__DummyModuleLock':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:184:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  184 |     """Check if 'target_id' is holding the same lock as another thread(s).
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py: In function '_alloc__ImportLockContext':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:198:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  198 |     """
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py: In function '_alloc__List':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:212:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  212 |             # This means we would not actually deadlock.  This can happen if
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py: In function '_alloc__ModuleLock':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:226:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  226 | class _ModuleLock:
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py: In function '_alloc__ModuleLockManager':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:240:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  240 |         #  -> ...
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py: In function '_alloc__WeakValueDictionary':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:254:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  254 |         self.wakeup = _thread.allocate_lock()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py: In function '_object_name_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:32:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   32 | _thread = None
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:916:10: warning: unused variable '_t6' [-Wunused-variable]
  916 |     if spec.loader is not None:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py: In function '_wrap_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:73:7: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
   73 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:37:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   37 | _bootstrap_external = None
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py: In function '_WeakValueDictionary___init__':
/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap.py:65:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   65 |         self_weakref = _weakref.ref(self)
... (3947 more lines)
```

Exit code: 1
Elapsed: 10.36s
