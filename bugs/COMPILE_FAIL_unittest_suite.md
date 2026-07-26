# COMPILE_FAIL: Lib/unittest/suite.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py: In function '_alloc__DebugResult':
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:68:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   68 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py: In function '_alloc__ErrorHolder':
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:82:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   82 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py: In function '_call_if_exists_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:292:11: warning: variable 'func' set but not used [-Wunused-but-set-variable]
  292 |         if getattr(result, '_moduleSetUpFailed', False):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py: In function 'BaseTestSuite___init__':
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:22:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   22 |         self._tests = []
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:20:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   20 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:19:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   19 |     _cleanup = True
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:18:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   18 |     """
      |              ^  
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:17:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   17 |     """A simple test suite that doesn't provide class or module shared fixtures.
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py: In function 'BaseTestSuite___repr__':
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:45:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   45 |         # sanity checks
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:32:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   32 |         return list(self) == list(other)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py: In function 'BaseTestSuite___eq__':
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:34:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   34 |     def __iter__(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:45:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   45 |         # sanity checks
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:40:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   40 |             if test:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:38:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   38 |         cases = self._removed_tests
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/suite.py:37:9: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
... (2919 more lines)
```

Exit code: 1
Elapsed: 14.21s
