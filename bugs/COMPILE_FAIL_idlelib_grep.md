# COMPILE_FAIL: Lib/idlelib/grep.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py: In function '_alloc_GrepDialog':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:71:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   71 |     def __init__(self, root, engine, flist):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py: In function 'grep_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:354:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:353:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:351:11: warning: variable 'searchphrase' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:349:10: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:320:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py: In function 'walk_error_584a43':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:45:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   45 |     print(msg)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py: In function 'findfiles_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:53:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   53 |         pattern: File pattern to match.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:52:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   52 |         folder: Root directory to search.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:50:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   50 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py: In function 'GrepDialog___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:75:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   75 |         searchengine instance to prepare the search.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:73:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   73 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:72:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   72 |         """Create search dialog for searching for a phrase in the file system.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:71:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   71 |     def __init__(self, root, engine, flist):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:70:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   70 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:69:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   69 |     needwrapbutton = 0
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:68:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   68 |     icon = "Grep"
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/grep.py:67:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   67 |     title = "Find in Files Dialog"
      |           ^~~
... (939 more lines)
```

Exit code: 1
Elapsed: 12.19s
