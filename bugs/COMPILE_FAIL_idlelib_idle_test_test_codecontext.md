# COMPILE_FAIL: Lib/idlelib/idle_test/test_codecontext.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py: In function '_alloc_DummyEditwin':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:115:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  115 |         eq(cc.editwin, ed)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py: In function 'DummyEditwin___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:378:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  378 |         cc.update_font()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:376:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  376 |         # Call the font update, change is picked up.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:375:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  375 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:374:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  374 |         eq(cc.context['font'], test_font)
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:373:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  373 |         cc.toggle_code_context_event()
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:372:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  372 |         # Activate code context, previous font change is immediately effective.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:371:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  371 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:370:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  370 |         cc.update_font()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:369:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  369 |         # Nothing breaks or changes with inactive code context.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py: In function 'DummyEditwin_getlineno':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:56:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   56 |     def setUpClass(cls):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:54:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   54 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:53:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   53 | class CodeContextTest(unittest.TestCase):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:52:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   52 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:51:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   51 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_codecontext.py:50:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
... (4232 more lines)
```

Exit code: 1
Elapsed: 11.68s
