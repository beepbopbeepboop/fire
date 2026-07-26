# COMPILE_FAIL: Lib/idlelib/searchengine.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py: In function '_alloc_SearchEngine':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:45:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   45 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py: In function 'get_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:280:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py: In function 'SearchEngine___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:37:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   37 |     def getpat(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:35:7: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   35 |     # Access methods
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:34:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   34 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:33:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   33 |         self.backvar = BooleanVar(root, False)   # search backwards?
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:32:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   32 |         self.wrapvar = BooleanVar(root, True)   # wrap around buffer?
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:31:7: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   31 |         self.wordvar = BooleanVar(root, False)   # match whole word?
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:30:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   30 |         self.casevar = BooleanVar(root, False)   # match case?
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:29:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   29 |         self.revar = BooleanVar(root, False)   # regular expression?
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:28:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   28 |         self.patvar = StringVar(root, '')   # search pattern
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:27:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   27 |         self.root = root  # need for report_error()
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:26:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   26 |         '''
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:25:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   25 |         The dialogs bind these to the UI elements present in the dialogs.
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:24:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   24 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/searchengine.py:23:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   23 |         '''Initialize Variables that save search state.
      |          ^~~
... (890 more lines)
```

Exit code: 1
Elapsed: 10.49s
