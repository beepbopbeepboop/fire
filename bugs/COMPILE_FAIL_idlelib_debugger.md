# COMPILE_FAIL: Lib/idlelib/debugger.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py: In function '_alloc_Idb':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:148:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  148 |         if self.nesting_level > 0:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py: In function '_alloc_NamespaceViewer':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:162:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  162 |         except Exception:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py: In function '_alloc_StackViewer':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:176:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  176 |     def make_gui(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py: In function 'Idb___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:536:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  536 |         self.load_dict(odict)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:534:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  534 |         self.subframe = subframe = Frame(canvas)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:533:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  533 |         canvas["yscrollcommand"] = vbar.set
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:532:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  532 |         vbar["command"] = canvas.yview
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py: In function 'Idb_user_line':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:50:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   50 |     def user_exception(self, frame, exc_info):
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:60:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   60 |     if frame.f_code.co_filename.count('rpc.py'):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:53:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   53 |             self.set_step()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:53:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   53 |             self.set_step()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:50:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   50 |     def user_exception(self, frame, exc_info):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:46:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   46 |             self.gui.interaction(message, frame)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:43:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   43 |             return
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger.py:62:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   62 |     else:
... (3780 more lines)
```

Exit code: 1
Elapsed: 12.22s
