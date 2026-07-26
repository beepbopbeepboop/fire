# COMPILE_FAIL: CC ERROR: redefinition of 'X'

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py: In function '_alloc__Database':
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:41:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   41 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py: In function '_normalize_uri_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:117:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  117 |             self._cx.close()
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:115:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  115 |     def close(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:112:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  112 |         except sqlite3.Error as exc:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py: In function 'sqlite3__Database___init__':
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:80:1: warning: label 'bb_27' defined but not used [-Wunused-label]
   80 |         if not self._cx:
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:84:1: warning: label 'bb_26' defined but not used [-Wunused-label]
   84 |         except sqlite3.Error as exc:
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:83:1: warning: label 'bb_25' defined but not used [-Wunused-label]
   83 |             return closing(self._cx.execute(*args, **kwargs))
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:100:1: warning: label 'bb_24' defined but not used [-Wunused-label]
  100 |         self._execute(STORE_KV, (key, value))
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:88:1: warning: label 'bb_23' defined but not used [-Wunused-label]
   88 |         with self._execute(GET_SIZE) as cu:
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:81:1: warning: label 'bb_22' defined but not used [-Wunused-label]
   81 |             raise error(_ERR_CLOSED)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:91:1: warning: label 'bb_20' defined but not used [-Wunused-label]
   91 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:76:1: warning: label 'bb_18' defined but not used [-Wunused-label]
   76 |             if flag == "rwc":
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:71:1: warning: label 'bb_19' defined but not used [-Wunused-label]
   71 |         if flag != "ro":
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:67:1: warning: label 'bb_17' defined but not used [-Wunused-label]
   67 |             self._cx = sqlite3.connect(uri, autocommit=True, uri=True)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:70:1: warning: label 'bb_16' defined but not used [-Wunused-label]
   70 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:65:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   65 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:57:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   57 |                                  f"not {flag!r}")
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:81:1: warning: label 'bb_15' defined but not used [-Wunused-label]
   81 |             raise error(_ERR_CLOSED)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:53:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   53 |                 Path(path).unlink(missing_ok=True)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:72:1: warning: label 'bb_14' defined but not used [-Wunused-label]
   72 |             # This is an optimization only; it's ok if it fails.
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/dbm/sqlite3.py:50:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   50 |                 Path(path).touch(mode=mode, exist_ok=True)
      | ^ 
```

## Affected files

- `Lib/dbm/sqlite3.py`
