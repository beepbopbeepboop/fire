# COMPILE_FAIL: Lib/idlelib/stackviewer.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py: In function '_alloc_StackTreeItem':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:51:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   51 |     def __init__(self, info, flist):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py: In function '_alloc_VariablesTreeItem':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:65:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   65 |         sourceline = sourceline.strip()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py: In function 'StackBrowser_7a6366':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:306:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:299:19: warning: variable 'item' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:297:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:290:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py: In function 'StackTreeItem___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:27:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   27 |         self.text = f"{type(exc).__name__}: {str(exc)}"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:27:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   27 |         self.text = f"{type(exc).__name__}: {str(exc)}"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:27:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   27 |         self.text = f"{type(exc).__name__}: {str(exc)}"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:47:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   47 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:45:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   45 |             sublist.append(item)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:44:10: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   44 |             item = FrameTreeItem(info, self.flist)
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:43:7: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
   43 |         for info in self.stack:
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:42:10: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
   42 |         sublist = []
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:41:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
   41 |     def GetSubList(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:40:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
   40 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:39:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
   39 |         return self.text
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/stackviewer.py:38:10: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   38 |     def GetText(self):  # Titlecase names are overrides.
... (933 more lines)
```

Exit code: 1
Elapsed: 10.34s
