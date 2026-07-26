# COMPILE_FAIL: Lib/test/test_unittest/test_program.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py: In function '_alloc_FakeRunner':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:194:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  194 |             unittest.main(
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py: In function '_alloc_InitialisableProgram':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:208:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  208 |                 testLoader=self.TestLoader(self.SetUpClassFailure))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py: In function '_alloc_Test_TestProgram_test_discovery_from_dotted_path__find_tests_env':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:482:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  482 |         program = self.program
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py: In function 'Test_TestProgram_test_discovery_from_dotted_path__find_tests':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:497:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  497 |         # leaving the current error message (import of filename fails) in place?
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:494:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  494 |         # it would also be better to check that a filename is a valid module
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py: In function 'Test_TestProgram_test_discovery_from_dotted_path':
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:70:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   70 |             raise AssertionError
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:68:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
   68 |         @unittest.expectedFailure
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:67:10: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
   67 |             raise AssertionError
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:66:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
   66 |         def testSkipped(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:65:10: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
   65 |         @unittest.skip('skipping')
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:64:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
   64 |             1/0
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:63:9: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
   63 |         def testError(self):
      |         ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:62:11: warning: variable 'suite' set but not used [-Wunused-but-set-variable]
   62 |             raise AssertionError
      |           ^ ~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:61:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   61 |         def testFail(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_unittest/test_program.py:60:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
   60 |             pass
... (3709 more lines)
```

Exit code: 1
Elapsed: 14.36s
