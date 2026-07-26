# COMPILE_FAIL: Lib/test/test_unittest/test_setups.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:51:11: warning: unused variable '_tag' [-Wunused-variable]
   51 |         class Test(unittest.TestCase):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
   56 |                 unittest.TestCase.tearDownClass()
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:61:11: warning: unused variable '_tag' [-Wunused-variable]
   61 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:76:11: warning: unused variable '_tag' [-Wunused-variable]
   76 |                 pass
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:85:13: warning: unused variable '_tag' [-Wunused-variable]
   85 |                 unittest.TestCase.tearDownClass()
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py: In function 'TestSetups_getRunner':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:16:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   16 |     def runTests(self, *cases):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:14:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   14 |         return unittest.TextTestRunner(resultclass=resultFactory,
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:13:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   13 |     def getRunner(self):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py: In function 'TestSetups_runTests':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:29:3: error: expected expression before 'case'
   29 |         realSuite.addTest(unittest.TestSuite())
      |   ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:23:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   23 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:29:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   29 |         realSuite.addTest(unittest.TestSuite())
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:27:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   27 |         # adding empty suites to the end exposes potential bugs
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:23:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   23 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_setups.py:60:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   60 |                 pass
      | ^   
... (2513 more lines)
```

Exit code: 1
Elapsed: 14.47s
