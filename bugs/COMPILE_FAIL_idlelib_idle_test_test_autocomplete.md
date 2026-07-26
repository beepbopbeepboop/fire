# COMPILE_FAIL: Lib/idlelib/idle_test/test_autocomplete.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py: In function '_alloc_DummyEditwin':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:112:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  112 |         trycompletions()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py: In function 'DummyEditwin___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:367:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:365:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:364:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:363:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:362:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:361:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:360:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:359:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:358:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py: In function 'AutoCompleteTest_setUpClass':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:59:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   59 |         self.assertIsNone(acp.autocompletewindow)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:57:10: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
   57 |         acp._remove_autocomplete_window()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:56:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   56 |         acp.autocompletewindow = m = Mock()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:55:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
   55 |         acp = self.autocomplete
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:54:10: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
   54 |     def test_remove_autocomplete_window(self):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:53:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
   53 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:52:10: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
   52 |         self.assertIsInstance(testwin, acw.AutoCompleteWindow)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:51:10: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
   51 |         testwin = self.autocomplete._make_autocomplete_window()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:50:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
   50 |     def test_make_autocomplete_window(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:49:10: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
   49 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:48:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   48 |         self.assertEqual(self.autocomplete.text, self.text)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_autocomplete.py:47:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
... (2497 more lines)
```

Exit code: 1
Elapsed: 11.93s
