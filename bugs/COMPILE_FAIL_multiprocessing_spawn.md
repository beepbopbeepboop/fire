# COMPILE_FAIL: Lib/multiprocessing/spawn.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 |         _python_exe = os.fsdecode(exe)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:46:11: warning: unused variable '_tag' [-Wunused-variable]
   46 |     return _python_exe
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:51:11: warning: unused variable '_tag' [-Wunused-variable]
   51 |     set_executable(sys.executable)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:75:13: warning: unused variable '_tag' [-Wunused-variable]
   75 |             if value == 'None':
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py: In function 'set_executable_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:252:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  252 |     # their "main only" code unconditionally, so we don't even try to
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:249:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  249 | # spawned subprocesses
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:237:11: warning: variable '_python_exe' set but not used [-Wunused-but-set-variable]
  237 |     if 'orig_dir' in data:
      |           ^~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py: In function 'is_forking_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:51:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   51 |     set_executable(sys.executable)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py: In function 'freeze_support':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:125:11: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
  125 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:87:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   87 |     if getattr(sys, 'frozen', False):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:72:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   72 |         kwds = {}
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py: In function 'get_command_line_08efcc':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:88:15: error: invalid operands to binary % (have 'char *' and 'int64_t' {aka 'long long int'})
   88 |         return ([sys.executable, '--multiprocessing-fork'] +
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/spawn.py:92:15: error: invalid operands to binary % (have 'char *' and 'char *')
... (164 more lines)
```

Exit code: 1
Elapsed: 9.71s
