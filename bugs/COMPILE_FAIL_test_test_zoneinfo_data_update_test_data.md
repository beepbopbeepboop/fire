# COMPILE_FAIL: Lib/test/test_zoneinfo/data/update_test_data.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:45:11: warning: unused variable '_tag' [-Wunused-variable]
   45 |     for path in map(pathlib.Path, zoneinfo.TZPATH):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
   50 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:55:11: warning: unused variable '_tag' [-Wunused-variable]
   55 |     tzdata_zi = path / "tzdata.zi"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:70:11: warning: unused variable '_tag' [-Wunused-variable]
   70 |         raise ValueError(
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:79:13: warning: unused variable '_tag' [-Wunused-variable]
   79 | def get_zoneinfo(key: str) -> bytes:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py: In function 'get_zoneinfo_path':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:53:20: error: passing argument 1 of 'mojo_map' makes pointer from integer without a cast [-Wint-conversion]
   53 |     path = get_zoneinfo_path()
      |                    ^~~
      |                    |
      |                    int64_t {aka long long int}
In file included from update_test_data.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:333:22: note: expected 'void *' but argument is of type 'int64_t' {aka 'long long int'}
  333 | void *mojo_map(void *func, void *iterable);
      |                ~~~~~~^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:53:25: error: passing argument 2 of 'mojo_map' makes pointer from integer without a cast [-Wint-conversion]
   53 |     path = get_zoneinfo_path()
      |                         ^~~
      |                         |
      |                         int64_t {aka long long int}
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:333:34: note: expected 'void *' but argument is of type 'int64_t' {aka 'long long int'}
  333 | void *mojo_map(void *func, void *iterable);
      |                            ~~~~~~^~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:53:8: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
   53 |     path = get_zoneinfo_path()
      |        ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:191:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:182:10: warning: variable 'key' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:180:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py: In function 'get_zoneinfo_metadata':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:85:11: warning: variable '_' set but not used [-Wunused-but-set-variable]
   85 | 
      |           ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/data/update_test_data.py:80:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
... (68 more lines)
```

Exit code: 1
Elapsed: 13.28s
