# COMPILE_FAIL: Lib/test/test_unittest/test_result.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:198:11: warning: unused variable '_tag' [-Wunused-variable]
  198 |         self.assertFalse(result.wasSuccessful())
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:203:11: warning: unused variable '_tag' [-Wunused-variable]
  203 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:208:11: warning: unused variable '_tag' [-Wunused-variable]
  208 |     def test_addFailure_filter_traceback_frames(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:223:11: warning: unused variable '_tag' [-Wunused-variable]
  223 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:232:13: warning: unused variable '_tag' [-Wunused-variable]
  232 |         self.assertIn("raise self.failureException(msg)", dropped[0])
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py: In function 'Test_TestResult_test_init':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:79:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   79 |         result.startTest(test)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:77:11: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
   77 |         result = unittest.TestResult()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:76:10: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
   76 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:75:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
   75 |         test = Foo('test_1')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:74:10: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
   74 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:73:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
   73 |                 pass
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:72:10: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   72 |             def test_1(self):
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:71:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
   71 |         class Foo(unittest.TestCase):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:70:10: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
   70 |     def test_startTest(self):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_result.py:69:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
... (9886 more lines)
```

Exit code: 1
Elapsed: 14.39s
