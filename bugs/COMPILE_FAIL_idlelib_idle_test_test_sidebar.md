# COMPILE_FAIL: Lib/idlelib/idle_test/test_sidebar.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py: In function '_alloc_Dummy_editwin':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:226:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  226 |         self.assertEqual(get_width(), 3)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py: In function 'Dummy_editwin___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:581:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  581 |         self.assertNotEqual(with_block_sidebar_lines, initial_sidebar_lines)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:579:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  579 |         self.assert_sidebar_lines_end_with(['>>>', '...', '...'])
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:578:7: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  578 |         yield
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:577:7: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  577 |             '''))
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:576:7: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  576 |             print(1)
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:575:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  575 |             if True:
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:574:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  574 |         self.do_input(dedent('''\
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:573:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  573 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:572:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  572 |         initial_sidebar_lines = self.get_sidebar_lines()
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:571:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  571 |         # Block statements are not indented because IDLE auto-indents.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:570:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  570 |         text = self.shell.text
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:569:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  569 |     def test_interrupt_recall_undo_redo(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:568:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  568 |     @run_in_tk_mainloop()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:567:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  567 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py: In function 'Dummy_editwin_setvar':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_sidebar.py:35:1: warning: label 'bb_2' defined but not used [-Wunused-label]
... (6404 more lines)
```

Exit code: 1
Elapsed: 11.12s
