# COMPILE_FAIL: Lib/idlelib/tree.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py: In function '_alloc_FileTreeItem':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:99:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   99 |         for c in self.children[:]:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py: In function '_alloc_ScrolledCanvas':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:113:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  113 |         self.iconimages[name] = image
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py: In function '_alloc_TreeNode':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:127:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  127 |             return
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py: In function 'listicons_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:601:7: warning: variable 'column' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:600:7: warning: variable 'row' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:597:7: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:587:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:585:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:580:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py: In function 'wheel_event_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:109:11: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
  109 |         file, ext = os.path.splitext(name)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:108:10: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
  108 |             pass
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:107:11: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
  107 |         except KeyError:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:98:11: warning: variable 'lines' set but not used [-Wunused-but-set-variable]
   98 |     def destroy(self):
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:62:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   62 |     For wheel up, event.delta = 120*n on Windows, -1*n on darwin,
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py: In function 'TreeNode___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:101:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  101 |             c.destroy()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:99:14: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   99 |         for c in self.children[:]:
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:98:14: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   98 |     def destroy(self):
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:97:7: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   97 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tree.py:96:7: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
... (3267 more lines)
```

Exit code: 1
Elapsed: 10.28s
