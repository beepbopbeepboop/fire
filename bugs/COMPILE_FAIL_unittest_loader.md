# COMPILE_FAIL: Lib/unittest/loader.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py: In function '_alloc_TestLoader':
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:96:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   96 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py: In function '_alloc__FailedTest':
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:110:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  110 |         tests = self.suiteClass(tests)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py: In function '_FailedTest___init__':
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:364:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  364 |         return name
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:362:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  362 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:361:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  361 |         assert not _relpath.startswith('..'), "Path must be within the project"
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:360:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  360 |         assert not os.path.isabs(_relpath), "Path must be within the project"
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:359:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  359 |         _relpath = os.path.relpath(path, self._top_level_dir)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:358:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  358 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py: In function '_alloc__FailedTest___getattr___testFailure_env':
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:35:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   35 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py: In function '_FailedTest___getattr___testFailure':
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:44:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   44 |     return _make_failed_test(
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py: In function '_FailedTest___getattr__':
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:34:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   34 |         return testFailure
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:67:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   67 |     """
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:61:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   61 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:59:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   59 | def _splitext(path):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/loader.py:58:17: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
... (2921 more lines)
```

Exit code: 1
Elapsed: 14.18s
