# COMPILE_FAIL: Lib/idlelib/debugobj_r.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py: In function '_alloc_WrappedObjectTreeItem':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:26:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   26 |     def __init__(self, sockio, oid):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py: In function 'WrappedObjectTreeItem___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:14:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   14 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:12:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   12 |     def __init__(self, item):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py: In function 'WrappedObjectTreeItem___getattr__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:26:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   26 |     def __init__(self, sockio, oid):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:24:11: warning: variable 'value' set but not used [-Wunused-but-set-variable]
   24 |     # Lives in IDLE process
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:23:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   23 | class StubObjectTreeItem:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:22:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   22 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:21:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   21 |         return list(map(remote_object_tree_item, sub_list))
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:20:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   20 |         sub_list = self.__item._GetSubList()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:19:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   19 |     def _GetSubList(self):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:18:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   18 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py: In function 'WrappedObjectTreeItem__GetSubList':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:27:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   27 |         self.sockio = sockio
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:24:11: warning: variable 'sub_list' set but not used [-Wunused-but-set-variable]
   24 |     # Lives in IDLE process
      |           ^~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py: In function 'StubObjectTreeItem___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:29:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   29 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj_r.py:27:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   27 |         self.sockio = sockio
... (76 more lines)
```

Exit code: 1
Elapsed: 12.00s
