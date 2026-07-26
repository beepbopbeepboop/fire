# COMPILE_FAIL: Lib/idlelib/idle_test/test_debugger.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py: In function '_alloc_MockFrame':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:134:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  134 |     def test_set_load_breakpoints(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py: In function 'MockFrame___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:353:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:351:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:350:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py: In function 'IdbTest_setUpClass':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:80:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   80 |         code_frame = MockFrame(code_obj, 1)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:78:10: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
   78 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:77:11: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
   77 |                          'rpc.py:2: <module>()')
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:76:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
   76 |         self.assertEqual(debugger._frame2message(rpc_frame),
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:75:10: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
   75 |         self.assertTrue(debugger._in_rpc_code(rpc_frame))
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:74:11: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
   74 |         rpc_frame.f_back = rpc_frame
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:73:10: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
   73 |         rpc_frame = MockFrame(rpc_obj, 2)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:72:10: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
   72 |         rpc_obj = compile(TEST_CODE,'rpc.py', mode='exec')
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:71:10: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
   71 |     def test_functions(self):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:70:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
   70 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:69:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
   69 |     # Test module functions together.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:68:10: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
   68 | class FunctionTest(unittest.TestCase):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:67:15: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   67 | 
      |               ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_debugger.py:66:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
... (2229 more lines)
```

Exit code: 1
Elapsed: 12.36s
