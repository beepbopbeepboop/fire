# COMPILE_FAIL: CC ERROR: returning 'X' from a function with return type 'X' makes integer from pointer without a cast [-Wint-conversion]

**8 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py:15:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py:20:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py:25:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py:40:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py:49:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py: In function 'main':
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py:14:10: error: returning 'char *' from a function with return type 'int' makes integer from pointer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py:67:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py:38:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py:29:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py:24:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py:19:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py:14:16: warning: '_mojo_dispatch_getattr' defined but not used [-Wunused-function]
__init__.ci:457:16: warning: 'id' defined but not used [-Wunused-function]
  457 | static int64_t id (int64_t x) { return x; }
      |                ^~
__init__.ci:456:19: warning: '_Bool_items' defined but not used [-Wunused-function]
  456 | static MojoList * _Bool_items (int64_t a) { return mojo_list_new(); }
      |                   ^~~~~~~~~~~
__init__.ci:455:15: warning: '_ReflectTable_in_dll' defined but not used [-Wunused-function]
  455 | static char * _ReflectTable_in_dll (int64_t a, int64_t b, char * c) { return (char *)dlsym((void *)b, c); }
      |               ^~~~~~~~~~~~~~~~~~~~
In file included from __init__.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:396:12: warning: '_mojo_vprintf' defined but not used [-Wunused-function]
  396 | static int _mojo
```

## Affected files

- `Lib/test/test_importlib/metadata/data/sources/example/example/__init__.py`
- `Lib/test/test_importlib/metadata/data/sources/example2/example2/__init__.py`
- `Lib/turtledemo/chaos.py`
- `Lib/turtledemo/nim.py`
- `Lib/turtledemo/peace.py`
- `Lib/turtledemo/planet_and_moon.py`
- `Lib/turtledemo/two_canvases.py`
- `Lib/turtledemo/yinyang.py`
