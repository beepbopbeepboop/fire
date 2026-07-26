# COMPILE_FAIL: Lib/multiprocessing/util.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:112:11: warning: unused variable '_tag' [-Wunused-variable]
  112 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:117:11: warning: unused variable '_tag' [-Wunused-variable]
  117 |         return address[0] == 0
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:122:11: warning: unused variable '_tag' [-Wunused-variable]
  122 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:137:11: warning: unused variable '_tag' [-Wunused-variable]
  137 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:146:13: warning: unused variable '_tag' [-Wunused-variable]
  146 | def _remove_temp_dir(rmtree, tempdir):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py: In function 'sub_debug':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:385:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  385 |     Returns true if the process is shutting down
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:384:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  384 |     '''
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py: In function 'debug':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:61:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   61 | def sub_warning(msg, *args):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:60:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   60 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py: In function 'info':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:65:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   65 | def get_logger():
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:64:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   64 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py: In function 'warn':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:69:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   69 |     global _logger
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py:68:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   68 |     '''
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/util.py: In function 'sub_warning':
... (1038 more lines)
```

Exit code: 1
Elapsed: 9.82s
