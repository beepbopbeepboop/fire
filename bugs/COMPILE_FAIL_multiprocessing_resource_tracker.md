# COMPILE_FAIL: Lib/multiprocessing/resource_tracker.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py: In function '_alloc_ResourceTracker':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:92:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   92 |         # making sure child processess are cleaned before ResourceTracker
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py: In function 'ResourceTracker___init__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:384:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  384 | _fork_intent = threading.local()
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:382:9: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  382 | # tracker.  Using threading.local() keeps multiple threads calling
      |         ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:381:9: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  381 | # where the child instead closes the fd so the parent's __del__ can reap the
      |         ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:380:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  380 | # the child can reuse this tracker (gh-80849).  Unset for raw os.fork() calls,
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:379:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  379 | # os.fork(), telling _after_fork_in_child() to keep the inherited pipe fd so
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:378:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  378 | # gh-146313: Per-thread flag set by .popen_fork.Popen._launch() just before
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:377:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  377 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:376:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  376 |         self._ensure_running_and_write(msg)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:375:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  375 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:374:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  374 |         assert msg.startswith(b'{')
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:373:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  373 |         assert len(msg) <= 512, f"internal error: message too long ({len(msg)} bytes)"
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py: In function 'ResourceTracker__reentrant_call_error':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:88:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   88 |         raise ReentrantCallError(
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:86:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   86 |         # that itself calls back into ResourceTracker.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py: In function 'ResourceTracker___del__':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/resource_tracker.py:102:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  102 |         # The tracker process is a child of the *parent*, not of us, so we
      | ^   
... (1670 more lines)
```

Exit code: 1
Elapsed: 9.75s
