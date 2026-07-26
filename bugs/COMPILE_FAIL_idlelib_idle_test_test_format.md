# COMPILE_FAIL: Lib/idlelib/idle_test/test_format.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py: In function '_alloc_DummyEditwin':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:179:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  179 |         # Test with leading newline
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py: In function '_alloc_Editor':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:193:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  193 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py: In function '_alloc_TextWrapper':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:207:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  207 |         result = ft.reformat_comment(test_comment, 70, "#")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py: In function 'Is_Get_Test_test_is_all_white':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:569:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  569 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:567:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  567 |         self.assertIsNotNone(untabify())
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:566:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  566 |         _asktabwidth.return_value = 3
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:565:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  565 |         self.formatter.tabify_region_event()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:564:7: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
  564 |         _asktabwidth.return_value = 2
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:563:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  563 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:562:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  562 |         self.assertIsNone(untabify())
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:561:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  561 |         _asktabwidth.return_value = None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:560:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  560 |         # No tabwidth selected.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:559:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  559 |         text.tag_add('sel', '7.0', '10.0')
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:558:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  558 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_format.py:557:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  557 |         eq = self.assertEqual
      |          ^~~
... (4376 more lines)
```

Exit code: 1
Elapsed: 10.21s
