# COMPILE_FAIL: Lib/ctypes/util.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:49:11: warning: unused variable '_tag' [-Wunused-variable]
   49 |         # If python was built with in debug mode
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:59:11: warning: unused variable '_tag' [-Wunused-variable]
   59 |         for directory in os.environ['PATH'].split(os.pathsep):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:74:11: warning: unused variable '_tag' [-Wunused-variable]
   74 |     from ctypes import wintypes
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:83:13: warning: unused variable '_tag' [-Wunused-variable]
   83 |         wintypes.HMODULE,
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py: In function 'test':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:227:8: error: variable or field '_t20' declared void
  227 | 
      |        ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:500:10: warning: dereferencing 'void *' pointer
  500 |         print(cdll.load("msvcrt"))
      |          ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:500:8: error: invalid use of void expression
  500 |         print(cdll.load("msvcrt"))
      |        ^
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:417:11: warning: variable '_t210' set but not used [-Wunused-but-set-variable]
  417 |             if libpath:
      |           ^ ~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:416:10: warning: unused variable '_t209' [-Wunused-variable]
  416 |             libpath = os.environ.get('LD_LIBRARY_PATH')
      |          ^  ~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:399:10: warning: variable '_t192' set but not used [-Wunused-but-set-variable]
  399 |             regex = os.fsencode(regex % (re.escape(name), abi_type))
      |          ^  ~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:393:10: warning: variable '_t186' set but not used [-Wunused-but-set-variable]
  393 |                 'ia64-64': 'libc6,IA-64',
      |          ^    
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:387:10: warning: variable '_t180' set but not used [-Wunused-but-set-variable]
  387 |                 machine = os.uname().machine + '-64'
      |          ^    
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:374:10: warning: variable '_t167' set but not used [-Wunused-but-set-variable]
  374 | 
      |          ^    
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py:361:10: warning: variable '_t154' set but not used [-Wunused-but-set-variable]
... (72 more lines)
```

Exit code: 1
Elapsed: 9.51s
