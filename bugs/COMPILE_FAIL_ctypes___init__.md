# COMPILE_FAIL: Lib/ctypes/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py: In function '_alloc_LibraryLoader':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:283:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  283 |     if isinstance(cls, str):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py: In function '_alloc_PyDLL':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:297:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  297 | def pointer(obj):
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py: In function '_alloc__PointerTypeCache':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:311:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  311 |         try:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py: In function 'create_string_buffer_0c5bb1':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:672:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
  672 |     elif sizeof(kind) == 4: c_uint32 = kind
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:669:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
  669 |     elif sizeof(kind) == 8: c_int64 = kind
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:652:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  652 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:649:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  649 |             return -2147221231 # CLASS_E_CLASSNOTAVAILABLE
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py:632:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  632 |     from _ctypes import _wstring_at_addr
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
... (1043 more lines)
```

Exit code: 1
Elapsed: 9.41s
