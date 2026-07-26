# COMPILE_FAIL: CC ERROR: invalid conversion in gimple call

**29 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:64:11: warning: unused variable '_tag' [-Wunused-variable]
   64 |     def __new__(cls):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:69:11: warning: unused variable '_tag' [-Wunused-variable]
   69 | #        return f'interpreters._queues.UNBOUND'
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:74:11: warning: unused variable '_tag' [-Wunused-variable]
   74 | UNBOUND_REMOVE = object()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:89:11: warning: unused variable '_tag' [-Wunused-variable]
   89 |     except KeyError:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:98:13: warning: unused variable '_tag' [-Wunused-variable]
   98 |         raise NotImplementedError(f'unsupported unbound replacement op {flag!r}')
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function 'classonly___init__':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:186:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:184:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:183:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:182:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:181:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:180:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:179:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:178:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function 'classonly___set_name__':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:45:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   45 |             doc = doc.replace(
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:37:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   37 |     """
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:30:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   30 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:28:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   28 |         # called on the class
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:27:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   27 |             raise AttributeError(self.na
```

## Affected files

- `Lib/concurrent/interpreters/_crossinterp.py`
- `Lib/email/headerregistry.py`
- `Lib/http/client.py`
- `Lib/idlelib/config.py`
- `Lib/importlib/metadata/_collections.py`
- `Lib/multiprocessing/context.py`
- `Lib/multiprocessing/resource_sharer.py`
- `Lib/sqlite3/dbapi2.py`
- `Lib/test/libregrtest/filter.py`
- `Lib/test/test__opcode.py`
- `Lib/test/test_bool.py`
- `Lib/test/test_capi/test_function.py`
- `Lib/test/test_capi/test_type.py`
- `Lib/test/test_cext/__init__.py`
- `Lib/test/test_concurrent_futures/test_deadlock.py`
- `Lib/test/test_cppext/__init__.py`
- `Lib/test/test_ctypes/test_callbacks.py`
- `Lib/test/test_ctypes/test_memfunctions.py`
- `Lib/test/test_ctypes/test_parameters.py`
- `Lib/test/test_dataclasses/__init__.py`
- `Lib/test/test_free_threading/test_str.py`
- `Lib/test/test_json/test_unicode.py`
- `Lib/test/test_subclassinit.py`
- `Lib/test/test_tkinter/test_variables.py`
- `Lib/test/test_type_annotations.py`
- `Lib/test/test_urlparse.py`
- `Lib/textwrap.py`
- `Lib/turtledemo/lindenmayer.py`
- `PC/layout/support/filesets.py`
