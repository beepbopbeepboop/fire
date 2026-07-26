# COMPILE_FAIL: Lib/idlelib/textview.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py: In function '_alloc_AutoHideScrollbar':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:128:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  128 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py: In function '_alloc_ScrollableTextFrame':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:142:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  142 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py: In function '_alloc_ViewFrame':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:156:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  156 |     wrap - type of text wrapping to use ('word', 'char' or 'none')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py: In function '_alloc_ViewWindow':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:170:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  170 |     """
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py: In function 'AutoHideScrollbar_set':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:24:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   24 |     def pack(self, **kwargs):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:22:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   22 |         super().set(lo, hi)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:507:1: warning: label 'bb_6' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:504:1: warning: label 'bb_5' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:498:1: warning: label 'bb_4' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:494:1: warning: label 'bb_3' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:489:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:487:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:486:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:485:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:484:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:483:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:482:9: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:481:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:480:9: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:479:9: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:478:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py: In function 'AutoHideScrollbar_pack':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:33:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   33 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:31:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   31 | class ScrollableTextFrame(Frame):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:30:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   30 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/textview.py:29:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
... (586 more lines)
```

Exit code: 1
Elapsed: 10.44s
