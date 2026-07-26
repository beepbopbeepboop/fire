# COMPILE_FAIL: Lib/idlelib/filelist.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py: In function '_alloc_FileList':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:39:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   39 |                 return edit
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py: In function 'FileList___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:232:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:230:14: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:229:14: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:228:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:227:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:226:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:225:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:224:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py: In function 'FileList_mojo_open':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:45:1: warning: label 'bb_13' defined but not used [-Wunused-label]
   45 |         edit = self.open(filename)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:42:1: warning: label 'bb_14' defined but not used [-Wunused-label]
   42 |                 return None
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:45:1: warning: label 'bb_12' defined but not used [-Wunused-label]
   45 |         edit = self.open(filename)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:48:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   48 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:38:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   38 |             if edit.good_load:
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:40:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   40 |             else:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:35:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   35 |             return action(filename)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:35:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   35 |             return action(filename)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:30:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   30 |             edit = self.dict[key]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:27:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   27 |             return None
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:20:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   20 |         filename = self.canonize(filename)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/filelist.py:20:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   20 |         filename = self.canonize(filename)
... (754 more lines)
```

Exit code: 1
Elapsed: 12.05s
