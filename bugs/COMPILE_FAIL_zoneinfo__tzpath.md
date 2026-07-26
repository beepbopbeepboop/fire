# COMPILE_FAIL: Lib/zoneinfo/_tzpath.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:34:11: warning: unused variable '_tag' [-Wunused-variable]
   34 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:39:11: warning: unused variable '_tag' [-Wunused-variable]
   39 |     # This is how we equalize the stacklevel for both calls.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:44:11: warning: unused variable '_tag' [-Wunused-variable]
   44 |     if not env_var:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:59:11: warning: unused variable '_tag' [-Wunused-variable]
   59 |             InvalidTZPathWarning,
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:68:13: warning: unused variable '_tag' [-Wunused-variable]
   68 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py: In function '_reset_tzpath_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:57:20: error: passing argument 1 of 'mojo_map' makes pointer from integer without a cast [-Wint-conversion]
   57 |             "Invalid paths specified in PYTHONTZPATH environment variable. "
      |                    ^~~~
      |                    |
      |                    int64_t {aka long long int}
In file included from _tzpath.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:333:22: note: expected 'void *' but argument is of type 'int64_t' {aka 'long long int'}
  333 | void *mojo_map(void *func, void *iterable);
      |                ~~~~~~^~~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:57:26: error: passing argument 2 of 'mojo_map' makes pointer from integer without a cast [-Wint-conversion]
   57 |             "Invalid paths specified in PYTHONTZPATH environment variable. "
      |                          ^~~~~~~
      |                          |
      |                          int64_t {aka long long int}
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:333:34: note: expected 'void *' but argument is of type 'int64_t' {aka 'long long int'}
  333 | void *mojo_map(void *func, void *iterable);
      |                            ~~~~~~^~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:57:8: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
   57 |             "Invalid paths specified in PYTHONTZPATH environment variable. "
      |        ^
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:231:11: warning: variable '_t55' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:209:14: warning: variable 'base_tzpath' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:206:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:191:11: warning: variable 'p' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py: In function 'reset_tzpath_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/zoneinfo/_tzpath.py:37:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   37 |     # We need `_reset_tzpath` helper function because it produces a warning,
      |          ^~~
... (166 more lines)
```

Exit code: 1
Elapsed: 13.13s
