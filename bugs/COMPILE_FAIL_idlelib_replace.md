# COMPILE_FAIL: Lib/idlelib/replace.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py: In function '_alloc_ReplaceDialog':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:68:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   68 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py: In function 'replace_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:369:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:368:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:366:11: warning: variable 'searchphrase' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:364:10: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:335:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py: In function 'ReplaceDialog___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:42:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   42 |         searchengine instance to prepare the search.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:40:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   40 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:39:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   39 |         """Create search dialog for finding and replacing text.
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:38:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   38 |     def __init__(self, root, engine):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:37:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   37 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:36:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   36 |     icon = "Replace"
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:35:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   35 |     title = "Replace Dialog"
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:34:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   34 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py: In function 'ReplaceDialog_mojo_open':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:68:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   68 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:66:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   66 |         self.ok = True
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:65:9: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   65 |         SearchDialogBase.open(self, text, searchphrase)
      |         ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:64:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   64 |         """
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/replace.py:63:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
... (1797 more lines)
```

Exit code: 1
Elapsed: 10.48s
