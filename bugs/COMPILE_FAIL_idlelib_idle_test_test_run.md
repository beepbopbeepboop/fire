# COMPILE_FAIL: Lib/idlelib/idle_test/test_run.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py: In function '_alloc_MockShell':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:197:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  197 |         self.assertEqual(f.readlines(0), ['one\n', 'two\n'])
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py: In function '_alloc_S':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:211:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  211 |         shell.push(['one\n', 'two\n', ''])
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py: In function 'ExceptionTest_test_print_exception_unhashable':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:39:1: warning: label 'bb_14' defined but not used [-Wunused-label]
   39 |         self.assertIn('UnhashableException: ex1', tb[10])
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:72:1: warning: label 'bb_13' defined but not used [-Wunused-label]
   72 |                     eval(compile(code1, '', 'eval'))
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:42:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   42 |             ('abc', NameError, "name 'abc' is not defined. "
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:57:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   57 |                     typ, val, tb = sys.exc_info()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:62:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   62 |     @force_not_colorized
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:45:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   45 |             ('int.reel', AttributeError,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:48:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   48 |             )
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:48:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   48 |             )
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:33:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   33 |                         ct.side_effect = lambda t, e: t
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:38:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   38 |         self.assertIn('UnhashableException: ex2', tb[3])
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:554:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:552:11: warning: variable '_t70' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:551:10: warning: variable '_t69' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:550:11: warning: variable '_t68' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:549:11: warning: variable '_t67' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:548:11: warning: variable '_t66' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:547:14: warning: variable '_t65' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:546:10: warning: variable '_t64' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:545:11: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_run.py:544:10: warning: variable '_t62' set but not used [-Wunused-but-set-variable]
... (4133 more lines)
```

Exit code: 1
Elapsed: 11.20s
