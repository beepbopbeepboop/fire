# COMPILE_FAIL: Lib/test/test_ttk_textonly.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py: In function '_alloc_MockStateSpec':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:88:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   88 |         check_against(
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py: In function '_alloc_MockTclObj':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:102:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  102 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py: In function '_alloc_MockTkApp':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:116:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  116 |                 {'option': ('{one}', 'two')}),
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py: In function 'MockTkApp_splitlist':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:17:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   17 |     def wantobjects(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:499:1: warning: label 'bb_3' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:490:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:488:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:487:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:486:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:485:14: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:484:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:483:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:482:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:481:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  481 |     unittest.main()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:480:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  480 | if __name__ == '__main__':
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:479:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  479 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:478:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  478 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:477:9: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  477 |             {'text': 'some text'})
      |         ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:476:9: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  476 |         self.assertEqual(ttk.tclobjs_to_py({'text': 'some text'}),
      |         ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:475:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  475 |     def test_nosplit(self):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ttk_textonly.py:474:7: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  474 | 
      |       ^  
... (3917 more lines)
```

Exit code: 1
Elapsed: 15.07s
