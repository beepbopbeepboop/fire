# COMPILE_FAIL: Lib/test/test_wmi.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:63:11: warning: unused variable '_tag' [-Wunused-variable]
   63 |     def test_wmi_query_overflow(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:68:11: warning: unused variable '_tag' [-Wunused-variable]
   68 |                 wmi_exec_query("SELECT * FROM CIM_DataFile")
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |         self.assertNotStartsWith(r, "\0")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:88:11: warning: unused variable '_tag' [-Wunused-variable]
   88 |             for t in task:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:97:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py: In function 'wmi_exec_query_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:189:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:187:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py: In function 'WmiTests_test_wmi_query_os_version':
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:85:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   85 |         query = "SELECT ProcessId FROM Win32_Process WHERE ProcessId < 1000"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:83:11: warning: variable '_t53' set but not used [-Wunused-but-set-variable]
   83 |     def test_wmi_query_threads(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:82:10: warning: variable '_t52' set but not used [-Wunused-but-set-variable]
   82 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:81:11: warning: variable '_t51' set but not used [-Wunused-but-set-variable]
   81 |             pass
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:80:11: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
   80 |         except StopIteration:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:79:11: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
   79 |                 self.assertEqual("", next(it))
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:78:14: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
   78 |                 self.assertRegex(next(it), r"ProcessId=\d+")
      |              ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:77:10: warning: variable '_t47' set but not used [-Wunused-but-set-variable]
   77 |             while True:
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wmi.py:76:11: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
   76 |         try:
      |           ^~  
... (590 more lines)
```

Exit code: 1
Elapsed: 12.44s
