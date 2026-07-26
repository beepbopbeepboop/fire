# COMPILE_FAIL: CC ERROR: passing argument N of 'X' makes integer from pointer without a cast [-Wint-conversion]

**12 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py: In function '_alloc_LibraryLoader':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:274:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  274 |     Pointer types are cached and reused internally,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py: In function '_alloc_PyDLL':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:288:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  288 |             return _pointer_type_cache_fallback[cls]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py: In function '_alloc__PointerTypeCache':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:302:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  302 |     should use byref(obj) which is much faster.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py: In function 'create_string_buffer_0c5bb1':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:647:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
  647 |             ccom = __import__("comtypes.server.inprocserver", globals(), locals(), ['*'])
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:644:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
  644 | if _os.name == "nt": # COM stuff
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:627:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  627 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:624:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  624 |     py_object, c_void_p, c_ssize_t, c_int)(_memoryview_at_addr)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:607:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  607 |         _argtypes_ = argtypes
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py: In function 'CFUNCTYPE_07077a':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:102:10: warning: unused variable '_t23' [-Wunused-variable]
  102 |     except KeyError:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:79:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   79 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py: In function 'py_object___repr__':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:166:21: error: passing argument 1 of 'mojo_type' makes integer from pointer without a cast [-Wint-conversion]
  166 |             return "%s(<NULL>)" % type(self).__name__
      |                     ^~~~
      |                     |
      |                     py_object *
In file included from __init__.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:317:19: note: expected 'int' but argument is of type 'py_object *'
  317 | int mojo_type(int obj);
      |               ~~~~^~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:166:15: error: invalid operands to binary % (have 'char *' and 'char *')
  166 |             return "%s(<NULL>)" % type(self).__name__
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:171:1: warning: label 'bb_5' defined but not used [-Wunused-label]
  171 |     _type_ = "h"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:196:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  196 |         _type_ = "I"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:192:7: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  192 |         _type_ = "i"
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:180:10: warning: unused variable '_t6' [-Wunused-variable]
  180 | _check_size(c_long)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/ct
```

## Affected files

- `Lib/concurrent/futures/__init__.py`
- `Lib/ctypes/__init__.py`
- `Lib/email/quoprimime.py`
- `Lib/sqlite3/__main__.py`
- `Lib/string/templatelib.py`
- `Lib/test/test__locale.py`
- `Lib/test/test_ast/utils.py`
- `Lib/test/test_opcache.py`
- `Lib/test/test_pathlib/support/lexical_path.py`
- `Lib/test/test_pathlib/support/zip_path.py`
- `Tools/c-analyzer/c_analyzer/info.py`
- `Tools/c-analyzer/c_parser/parser/_info.py`
