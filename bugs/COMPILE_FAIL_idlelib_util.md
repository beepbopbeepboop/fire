# COMPILE_FAIL: Lib/idlelib/util.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:25:11: warning: unused variable '_tag' [-Wunused-variable]
   25 | if sys.platform == 'win32':  # pragma: no cover
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:30:11: warning: unused variable '_tag' [-Wunused-variable]
   30 |             ctypes.OleDLL('shcore').SetProcessDpiAwareness(PROCESS_SYSTEM_DPI_AWARE)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:35:11: warning: unused variable '_tag' [-Wunused-variable]
   35 | if __name__ == '__main__':
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:59:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:37:3: error: implicit declaration of function '_gimple_main' [-Wimplicit-function-declaration]
   37 |     main('idlelib.idle_test.test_util', verbosity=2)
      |   ^ ~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:124:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:48:5: error: conflicting types for 'main'; have 'int(int,  const char **)'
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:100:16: note: previous declaration of 'main' with type 'int64_t()' {aka 'long long int()'}
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:59:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:77:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:48:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:39:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:34:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
   34 | 
      |                   ^                    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/util.py:29:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
   29 |             PROCESS_SYSTEM_DPI_AWARE = 1  # Int required.
      |             ^~~~~~~~~~~~~~~~~~~~~~
util.ci:458:16: warning: 'id' defined but not used [-Wunused-function]
  458 | static int64_t id (int64_t x) { return x; }
      |                ^~
util.ci:457:19: warning: '_Bool_items' defined but not used [-Wunused-function]
  457 | static MojoList * _Bool_items (int64_t a) { return mojo_list_new(); }
      |                   ^~~~~~~~~~~
util.ci:456:15: warning: '_ReflectTable_in_dll' defined but not used [-Wunused-function]
  456 | static char * _ReflectTable_in_dll (int64_t a, int64_t b, char * c) { return (char *)dlsym((void *)b, c); }
      |               ^~~~~~~~~~~~~~~~~~~~
In file included from util.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:396:12: warning: '_mojo_vprintf' defined but not used [-Wunused-function]
  396 | static int _mojo_vprintf(char *fmt, void *ap) {
      |            ^~~~~~~~~~~~~
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:392:16: warning: '_mojo_getline' defined but not used [-Wunused-function]
  392 | static ssize_t _mojo_getline(void *lp, void *n, void *f) {
... (5 more lines)
```

Exit code: 1
Elapsed: 10.04s
