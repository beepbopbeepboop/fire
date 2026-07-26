# COMPILE_FAIL: Lib/test/test_unittest/test_runner.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py: warning: f-string interpolation '{__name__ + '.' if __name__}' could not be compiled; emitting it as literal text (SyntaxError: 1:0: Expected KW got NEWLINE(''))
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py: warning: f-string interpolation '{__name__ + '.' if __name__}' could not be compiled; emitting it as literal text (SyntaxError: 1:0: Expected KW got NEWLINE(''))
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py: In function '_alloc_CustomError':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:326:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  326 |         runTests(TestableTest)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py: In function '_alloc_LacksEnter':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:340:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  340 |             @classmethod
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py: In function '_alloc_LacksEnterAndExit':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:354:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  354 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py: In function '_alloc_LacksExit':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:368:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  368 |         class TestableTest(unittest.TestCase):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py: In function '_alloc_TestCM':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:382:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  382 |             suite.debug()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py: In function 'runTests':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:47:8: error: expected expression before '=' token
   47 |     realSuite.addTest(unittest.TestSuite())
      |        ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:66:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
   66 |         return self.enter_result
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:64:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
   64 |     def __enter__(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:63:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
   63 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:60:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
   60 |     def __init__(self, ordering, enter_result=None):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:59:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
   59 | class TestCM:
      |           ^~~ 
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:56:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
   56 |         raise CustomError('CleanUpExc')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:55:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
   55 |         ordering.append('cleanup_exc')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_runner.py:46:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
   46 |     suite.addTest(unittest.TestSuite())
... (8739 more lines)
```

Exit code: 1
Elapsed: 14.67s
