# COMPILE_FAIL: Lib/test/test_winapi.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:88:11: warning: unused variable '_tag' [-Wunused-variable]
   88 |         self._events_waitany_test(16)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:93:11: warning: unused variable '_tag' [-Wunused-variable]
   93 |     def test_max_events_waitany(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:98:11: warning: unused variable '_tag' [-Wunused-variable]
   98 |     def test_getlongpathname(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:113:11: warning: unused variable '_tag' [-Wunused-variable]
  113 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:122:13: warning: unused variable '_tag' [-Wunused-variable]
  122 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py: In function 'WinAPIBatchedWaitForMultipleObjectsTests__events_waitall_test':
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:42:1: warning: label 'bb_23' defined but not used [-Wunused-label]
   42 |     def _events_waitany_test(self, n):
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:48:1: warning: label 'bb_24' defined but not used [-Wunused-label]
   48 |         # Choose 8 events to set, distributed throughout the list, to make sure
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:44:1: warning: label 'bb_22' defined but not used [-Wunused-label]
   44 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:40:1: warning: label 'bb_21' defined but not used [-Wunused-label]
   40 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:32:1: warning: label 'bb_19' defined but not used [-Wunused-label]
   32 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:32:1: warning: label 'bb_20' defined but not used [-Wunused-label]
   32 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:32:1: warning: label 'bb_18' defined but not used [-Wunused-label]
   32 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:32:1: warning: label 'bb_17' defined but not used [-Wunused-label]
   32 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:30:1: warning: label 'bb_16' defined but not used [-Wunused-label]
   30 |         # we don't always have them in the first chunk
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_winapi.py:39:1: warning: label 'bb_15' defined but not used [-Wunused-label]
... (1146 more lines)
```

Exit code: 1
Elapsed: 12.33s
