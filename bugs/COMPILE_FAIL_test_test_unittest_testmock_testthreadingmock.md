# COMPILE_FAIL: Lib/test/test_unittest/testmock/testthreadingmock.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py: In function '_alloc_Something':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:96:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   96 |         waitable_mock("works")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py: In function 'Something_method_1':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:282:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  282 |         try:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py: In function 'Something_method_2':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:23:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   23 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py: In function 'TestThreadingMock__call_after_delay':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:30:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   30 |         self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:28:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   28 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:27:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   27 |         func(*args, **kwargs)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:26:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   26 |         time.sleep(kwargs.pop("delay"))
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:25:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   25 |     def _call_after_delay(self, func, /, *args, **kwargs):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py: In function 'TestThreadingMock_setUp':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   38 |         )
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:36:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   36 |         self._executor.submit(
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:35:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   35 |     def run_async(self, func, /, *args, delay=0, **kwargs):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:34:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   34 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:33:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   33 |         self._executor.shutdown()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:32:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   32 |     def tearDown(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/testmock/testthreadingmock.py:31:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   31 | 
... (2372 more lines)
```

Exit code: 1
Elapsed: 15.25s
