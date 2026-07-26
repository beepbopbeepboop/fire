# COMPILE_FAIL: Lib/idlelib/pathbrowser.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py: In function '_alloc_DirBrowserTreeItem':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:53:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   53 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py: In function '_alloc_PathBrowserTreeItem':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:67:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   67 |         for nn, name, file in packages:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py: In function 'PathBrowser___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:242:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:240:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:239:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:238:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:237:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:236:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py: In function 'PathBrowser_settitle':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:37:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   37 |             item = DirBrowserTreeItem(dir)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:35:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   35 |         sublist = []
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:34:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   34 |     def GetSubList(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:33:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   33 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:32:7: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   32 |         return "sys.path"
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:31:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   31 |     def GetText(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:30:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   30 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:29:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   29 | class PathBrowserTreeItem(TreeItem):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:28:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   28 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:27:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   27 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pathbrowser.py:26:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   26 |         return PathBrowserTreeItem()
      |       ^ ~
... (246 more lines)
```

Exit code: 1
Elapsed: 10.65s
