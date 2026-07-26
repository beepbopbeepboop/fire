# COMPILE_FAIL: Lib/test/test_tkinter/test_variables.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py: In function '_alloc_Var':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:206:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  206 |         v.trace_remove('write', tr1)  # Wrong mode
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:423:41: warning: hex escape sequence out of range
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py: In function 'Var_set':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:440:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:438:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:437:9: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py: In function 'TestBase_setUp':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:28:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   28 |     def tearDown(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:26:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   26 |         self.root = Tcl()
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:25:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   25 |     def setUp(self):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py: In function 'TestBase_tearDown':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:34:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   34 |     def info_exists(self, *args):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:32:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   32 | class TestVariable(TestBase):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:31:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   31 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py: In function 'TestVariable_setUp':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   38 |         v = Variable(self.root)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:36:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   36 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:35:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   35 |         return self.root.getboolean(self.root.call("info", "exists", *args))
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py: In function 'TestVariable_tearDown':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:34:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   34 |     def info_exists(self, *args):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:32:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   32 | class TestVariable(TestBase):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tkinter/test_variables.py:31:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   31 | 
... (3377 more lines)
```

Exit code: 1
Elapsed: 61.76s
