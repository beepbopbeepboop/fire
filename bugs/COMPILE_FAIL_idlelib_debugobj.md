# COMPILE_FAIL: Lib/idlelib/debugobj.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:89:11: warning: unused variable '_tag' [-Wunused-variable]
   89 |                 continue
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:94:11: warning: unused variable '_tag' [-Wunused-variable]
   94 |         return sublist
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:99:11: warning: unused variable '_tag' [-Wunused-variable]
   99 |         keys = list(self.object)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:114:11: warning: unused variable '_tag' [-Wunused-variable]
  114 | }
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:123:13: warning: unused variable '_tag' [-Wunused-variable]
  123 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function 'ObjectTreeItem___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:270:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:268:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:267:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:266:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function 'ObjectTreeItem_GetLabelText':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:32:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   32 |             return "python"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:30:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   30 |     def GetIconName(self):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function 'ObjectTreeItem_GetText':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:36:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   36 |         try:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:34:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   34 |         return self.setfunction is not None
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:33:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   33 |     def IsEditable(self):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:32:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   32 |             return "python"
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function 'ObjectTreeItem_GetIconName':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:39:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   39 |         except:
      | ^   
... (1299 more lines)
```

Exit code: 1
Elapsed: 11.66s
