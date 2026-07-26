# COMPILE_FAIL: Lib/idlelib/browser.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py: In function '_alloc_ChildBrowserTreeItem':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:62:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   62 |                 obj.name += '({})'.format(', '.join(supers))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py: In function '_alloc_ModuleBrowserTreeItem':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:76:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   76 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py: In function 'is_browseable_extension_584a43':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:340:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:339:10: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:336:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:327:11: warning: variable '_' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py: In function 'transform_children_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:105:7: warning: variable '_t65' set but not used [-Wunused-but-set-variable]
  105 |         global file_open
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:96:10: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
   96 |         self.init()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:94:10: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
   94 |         self._htest = _htest
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:86:11: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
   86 |         Instance variables:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:37:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   37 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py: In function 'ModuleBrowser___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:76:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   76 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:74:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   74 |     def __init__(self, master, path, *, _htest=False, _utest=False):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:73:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   73 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:72:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   72 |     # PathBrowser.__init__ does not call __init__ below.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:71:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   71 |     # Init and close are inherited, other methods are overridden.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:70:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   70 |     # This class is also the base class for pathbrowser.PathBrowser.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/browser.py:69:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
... (881 more lines)
```

Exit code: 1
Elapsed: 10.18s
