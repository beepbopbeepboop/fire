# COMPILE_FAIL: CC ERROR: implicit declaration of function 'X' [-Wimplicit-function-declaration]

**17 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_CodeProxy':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:85:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   85 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_DictProxy':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:99:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   99 |             tb = tracebacktable[tbid]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_FrameProxy':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:113:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  113 |         msg = self.idb.clear_break(filename, lineno)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_GUIAdapter':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:127:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  127 |         frame = frametable[fid]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_GUIProxy':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:141:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  141 |         frame = frametable[fid]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_IdbAdapter':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:155:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  155 |         return code.co_filename
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py: In function '_alloc_IdbProxy':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:169:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  169 |     def dict_item(self, did, key):
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
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:76:14: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   76 | 
      |              ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:75:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   75 |     #----------called by an IdbProxy----------
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:74:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   74 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugger_r.py:73:14: warning: variable '_t8' set but not used [-Wunus
```

## Affected files

- `Lib/idlelib/debugger_r.py`
- `Lib/idlelib/debugobj_r.py`
- `Lib/idlelib/delegator.py`
- `Lib/idlelib/filelist.py`
- `Lib/idlelib/macosx.py`
- `Lib/idlelib/mainmenu.py`
- `Lib/idlelib/util.py`
- `Lib/operator.py`
- `Lib/test/test_android.py`
- `Lib/test/test_ctypes/test_c_simple_type_meta.py`
- `Lib/test/test_dbm_gnu.py`
- `Lib/test/test_largefile.py`
- `Lib/test/test_lzma.py`
- `Lib/test/test_profile.py`
- `Lib/test/test_sqlite3/test_transactions.py`
- `Lib/test/test_tabnanny.py`
- `Lib/tomllib/_re.py`
