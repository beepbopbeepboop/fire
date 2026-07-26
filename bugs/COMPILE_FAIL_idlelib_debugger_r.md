# COMPILE_FAIL: Lib/idlelib/debugger_r.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_CodeProxy':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:93:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   93 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_DictProxy':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:107:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  107 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_FrameProxy':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:121:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  121 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_GUIAdapter':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:135:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  135 |         ldict = frame.f_locals
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_GUIProxy':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:149:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  149 |     def code_name(self, cid):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_IdbAdapter':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:163:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  163 |     ### Needed until dict_keys type is finished and pickleable.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_IdbProxy':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:177:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  177 |     """Start the debugger and its RPC link in the Python subprocess
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function 'wrap_info_79c856':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:48:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   48 |         return None
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function 'GUIProxy___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:66:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   66 |         self.conn.remotecall(self.oid, "interaction",
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:64:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   64 |         # calls rpc.SocketIO.remotecall() via run.MyHandler instance
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:63:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   63 |     def interaction(self, message, frame, info=None):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function 'GUIProxy_interaction':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:79:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   79 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:77:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   77 |     def set_step(self):
      |           ^~~~
... (1420 more lines)
```

Exit code: 1
Elapsed: 11.83s
