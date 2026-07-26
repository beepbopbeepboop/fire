# COMPILE_FAIL: Lib/sqlite3/dbapi2.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |         warn(msg.format(what="timestamp converter"), DeprecationWarning, stacklevel=2)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:78:11: warning: unused variable '_tag' [-Wunused-variable]
   78 |         if len(timepart_full) == 2:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:83:11: warning: unused variable '_tag' [-Wunused-variable]
   83 |         val = datetime.datetime(year, month, day, hours, minutes, seconds, microseconds)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:98:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:107:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py: In function 'DateFromTicks_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:204:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py: In function 'TimeFromTicks_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:46:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   46 |     return Timestamp(*time.localtime(ticks)[:6])
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py: In function 'TimestampFromTicks_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:49:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   49 | sqlite_version_info = tuple([int(x) for x in sqlite_version.split(".")])
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py: In function '_alloc_register_adapters_and_converters_adapt_date_env':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:54:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   54 | def register_adapters_and_converters():
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py: In function 'register_adapters_and_converters_adapt_date':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:68:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   68 |     def convert_date(val):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:66:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   66 |         return val.isoformat(" ")
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:65:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   65 |         warn(msg.format(what="datetime adapter"), DeprecationWarning, stacklevel=2)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:64:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   64 |     def adapt_datetime(val):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:63:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   63 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/dbapi2.py:62:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   62 |         return val.isoformat()
      |          ^~~
... (256 more lines)
```

Exit code: 1
Elapsed: 10.05s
