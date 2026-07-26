# COMPILE_FAIL: Lib/sqlite3/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py: In function '_alloc_SqliteInteractiveConsole':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:49:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   49 |         Return False if input is a complete statement ready for execution.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py: In function 'execute_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:28:21: error: passing argument 1 of 'mojo_type' makes integer from pointer without a cast [-Wint-conversion]
   28 |         tp = type(e).__name__
      |                     ^~~~
      |                     |
      |                     char *
In file included from __main__.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:317:19: note: expected 'int' but argument is of type 'char *'
  317 | int mojo_type(int obj);
      |               ~~~~^~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:30:14: error: request for member 'sqlite_errorname' in something not a structure or union
   30 |             print(f"{tp} ({e.sqlite_errorname}): {e}", file=sys.stderr)
      |              ^~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:282:11: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:281:11: warning: variable '_t55' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:255:10: warning: unused variable '_t29' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:245:7: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:235:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:234:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:232:10: warning: unused variable '_t7' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:226:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py: In function 'SqliteInteractiveConsole___init__':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:55:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   55 |                 case "version":
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:53:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   53 |         if source[0] == ".":
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:52:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   52 |             return False
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:51:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   51 |         if not source or source.isspace():
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:50:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   50 |         """
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:49:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   49 |         Return False if input is a complete statement ready for execution.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:48:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   48 |         Return True if more input is needed; buffering is done automatically.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py: In function 'SqliteInteractiveConsole_runsource':
/Users/mrs/net/Python-3.14.6/Lib/sqlite3/__main__.py:114:14: error: expected ';' before 'as'
... (381 more lines)
```

Exit code: 1
Elapsed: 10.54s
