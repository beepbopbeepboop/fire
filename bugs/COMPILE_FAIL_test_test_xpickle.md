# COMPILE_FAIL: Lib/test/test_xpickle.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py:123:11: warning: unused variable '_tag' [-Wunused-variable]
  123 |                                   # For windows bpo-17023.
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py:128:11: warning: unused variable '_tag' [-Wunused-variable]
  128 |     @classmethod
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py:133:11: warning: unused variable '_tag' [-Wunused-variable]
  133 |         cls.worker = None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py:148:11: warning: unused variable '_tag' [-Wunused-variable]
  148 |         Returns:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py:157:13: warning: unused variable '_tag' [-Wunused-variable]
  157 |             worker.stdin.flush()
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py: In function 'highest_proto_for_py_version_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py:281:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  281 |     unittest.main()
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py: In function 'have_python_version_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py:68:24: error: passing argument 2 of 'mojo_map' makes pointer from integer without a cast [-Wint-conversion]
   68 |     python_str = ".".join(map(str, py_version))
      |                        ^~~~~~~~~~
      |                        |
      |                        int64_t {aka long long int}
In file included from test_xpickle.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:333:34: note: expected 'void *' but argument is of type 'int64_t' {aka 'long long int'}
  333 | void *mojo_map(void *func, void *iterable);
      |                            ~~~~~~^~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py:68:7: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
   68 |     python_str = ".".join(map(str, py_version))
      |       ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py:68:24: error: passing argument 2 of 'mojo_map' makes pointer from integer without a cast [-Wint-conversion]
   68 |     python_str = ".".join(map(str, py_version))
      |                        ^~~~~~~~~~
      |                        |
      |                        int64_t {aka long long int}
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:333:34: note: expected 'void *' but argument is of type 'int64_t' {aka 'long long int'}
  333 | void *mojo_map(void *func, void *iterable);
      |                            ~~~~~~^~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py:68:7: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
   68 |     python_str = ".".join(map(str, py_version))
      |       ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_xpickle.py:110:11: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
... (1983 more lines)
```

Exit code: 1
Elapsed: 13.14s
