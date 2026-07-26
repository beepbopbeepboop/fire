# COMPILE_FAIL: Lib/unittest/runner.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py: In function '_alloc__WritelnDecorator':
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:110:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  110 |         elif self.dots:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py: In function '_WritelnDecorator___init__':
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:341:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:339:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py: In function '_WritelnDecorator___getattr__':
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:56:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   56 |         else:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:51:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   51 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   38 |     separator2 = '-' * 70
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:36:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   36 |     """
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:35:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   35 |     Used by TextTestRunner.
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:34:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   34 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:33:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   33 |     """A test result class that can print formatted text results to a stream.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:32:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   32 | class TextTestResult(result.TestResult):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:31:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   31 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:30:9: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   30 | 
      |         ^  
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:29:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   29 |         self.write('\n')  # text-mode streams translate to \r\n if needed
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:28:8: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   28 |             self.write(arg)
      |        ^  
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:27:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   27 |         if arg:
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/unittest/runner.py:26:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   26 |     def writeln(self, arg=None):
... (2800 more lines)
```

Exit code: 1
Elapsed: 14.59s
