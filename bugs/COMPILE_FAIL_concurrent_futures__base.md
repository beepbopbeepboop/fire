# COMPILE_FAIL: Lib/concurrent/futures/_base.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_alloc__AcquireFutures':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:160:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  160 |         elif return_when == ALL_COMPLETED:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_alloc__AllCompletedWaiter':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:174:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  174 |     reverse order.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_alloc__AsCompletedWaiter':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:188:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  188 |         del f
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_alloc__FirstCompletedWaiter':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:202:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  202 |     Returns:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_Waiter___init__':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:549:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  549 |         self._invoke_callbacks()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:547:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  547 |                 waiter.add_result(self)
      |              ^  
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:546:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  546 |             for waiter in self._waiters:
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:545:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  545 |             self._state = FINISHED
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:544:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  544 |             self._result = result
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:543:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  543 |                 raise InvalidStateError('{}: {!r}'.format(self._state, self))
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_Waiter_add_result':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:65:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   65 |     def add_cancelled(self, future):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:63:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   63 |         self.finished_futures.append(future)
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:62:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   62 |     def add_exception(self, future):
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_Waiter_add_exception':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:68:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   68 | class _AsCompletedWaiter(_Waiter):
      | ^~~~
... (2362 more lines)
```

Exit code: 1
Elapsed: 9.51s
