# COMPILE_FAIL: CC ERROR: too few arguments to function 'X'; expected N, have N

**7 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_alloc__AcquireFutures':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:150:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  150 |     if return_when == _AS_COMPLETED:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_alloc__AllCompletedWaiter':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:164:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  164 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_alloc__AsCompletedWaiter':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:178:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  178 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_alloc__FirstCompletedWaiter':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:192:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  192 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_Waiter___init__':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:519:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  519 |         with self._condition:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:517:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  517 |                 set_result() or set_exception() was called.
      |              ^  
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:516:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  516 |             RuntimeError: if this method was already called or if
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:515:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  515 |         Raises:
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:514:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  514 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:513:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  513 |             False if the Future was cancelled, True otherwise.
      |           ^ ~
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
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:66:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   66 |         self.finished_futures.append(future)
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py:65:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   65 |     def add_cancelled(self, future):
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/_base.py: In function '_Waiter_add_cancelled':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/futur
```

## Affected files

- `Lib/concurrent/futures/_base.py`
- `Lib/ctypes/macholib/dyld.py`
- `Lib/test/test_import/data/double_const.py`
- `Lib/test/test_ntpath.py`
- `Lib/tkinter/font.py`
- `PC/layout/support/logging.py`
- `Tools/peg_generator/pegen/ast_dump.py`
