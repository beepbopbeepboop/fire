# COMPILE_FAIL: Lib/idlelib/idle_test/test_calltip.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py: In function '_alloc_TC':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:130:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  130 |                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n" + indent + "aaaaaaaaa"\
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py: In function '_alloc_WrappedCalltip':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:144:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  144 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py: In function '_alloc_mock_Shell':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:158:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  158 |         # Test max lines
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py: In function '_alloc_mock_TipWindow':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:172:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  172 |     def test_functions(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py: In function 'TC___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:547:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:545:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py: In function 'TC_t1':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:24:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   24 |     t3.tip = "(self, ai, *args)"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:22:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   22 |     t2.tip = "(self, ai, b=None)"
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py: In function 'TC_t2':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:26:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   26 |     t4.tip = "(self, *args)"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:24:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   24 |     t3.tip = "(self, ai, *args)"
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py: In function 'TC_t3':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:28:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   28 |     t5.tip = "(self, ai, b=None, *args, **kw)"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:26:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   26 |     t4.tip = "(self, *args)"
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py: In function 'TC_t4':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:30:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   30 |     t6.tip = "(no, self)"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:28:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   28 |     t5.tip = "(self, ai, b=None, *args, **kw)"
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py: In function 'TC_t5':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_calltip.py:32:1: warning: label 'bb_2' defined but not used [-Wunused-label]
... (2826 more lines)
```

Exit code: 1
Elapsed: 11.84s
