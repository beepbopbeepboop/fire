# COMPILE_FAIL: Lib/idlelib/window.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py: In function '_alloc_WindowList':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:78:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   78 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py: In function 'WindowList___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:252:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:250:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:249:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:248:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:247:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py: In function 'WindowList_add':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:25:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   25 |         for key in self.dict:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:23:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   23 |     def add_windows_to_menu(self,  menu):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:22:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   22 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:21:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   21 |         self.call_callbacks()
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:20:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   20 |             pass
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:19:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   19 |             # Sometimes, destroy() is called twice
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:18:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   18 |         except KeyError:
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:17:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   17 |             del self.dict[str(window)]
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:16:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   16 |         try:
      |           ^~ 
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:15:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   15 |     def delete(self, window):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:14:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   14 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py: In function 'WindowList_delete':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:22:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   22 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/window.py:31:1: warning: label 'bb_7' defined but not used [-Wunused-label]
... (698 more lines)
```

Exit code: 1
Elapsed: 10.09s
