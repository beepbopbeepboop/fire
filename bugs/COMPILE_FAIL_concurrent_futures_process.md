# COMPILE_FAIL: Lib/concurrent/futures/process.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py: In function '_alloc_BrokenProcessPool':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:184:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  184 |             self.thread_wakeup.wakeup()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py: In function '_alloc__CallItem':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:198:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  198 |     iterable passed to map.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py: In function '_alloc__ExceptionWithTraceback':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:212:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  212 |     except BaseException as e:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py: In function '_alloc__ExecutorManagerThread':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:226:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  226 |         result_queue: A ctx.Queue of _ResultItems that will written
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py: In function '_alloc__RemoteTraceback':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:240:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  240 |     exit_pid = None
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py: In function '_alloc__ResultItem':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:254:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  254 |             r = call_item.fn(*call_item.args, **call_item.kwargs)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py: In function '_alloc__SafeQueue':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:268:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  268 |         if exit_pid is not None:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py: In function '_alloc__ThreadWakeup':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:282:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  282 |     """
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py: In function '_alloc__WorkItem':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:296:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  296 |         # will wake up the queue management thread so that it can terminate
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py: In function '_ThreadWakeup___init__':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:841:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  841 |         Returns:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:839:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  839 |                 a task is submitted for each.
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:838:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  838 |                 If None, all input elements are eagerly collected, and
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/process.py:837:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  837 |                 iterables pauses until a result is yielded from the buffer.
      |           ^   
... (3847 more lines)
```

Exit code: 1
Elapsed: 9.55s
