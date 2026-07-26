# COMPILE_FAIL: Lib/ctypes/macholib/dyld.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:37:11: warning: unused variable '_tag' [-Wunused-variable]
   37 |     if env is None:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:42:11: warning: unused variable '_tag' [-Wunused-variable]
   42 |     return rval.split(':')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:47:11: warning: unused variable '_tag' [-Wunused-variable]
   47 |     return env.get('DYLD_IMAGE_SUFFIX')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:62:11: warning: unused variable '_tag' [-Wunused-variable]
   62 |     """For a potential path iterator, add DYLD_IMAGE_SUFFIX semantics"""
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:71:13: warning: unused variable '_tag' [-Wunused-variable]
   71 |                 yield path + suffix
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py: In function 'dyld_env_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:215:10: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py: In function 'dyld_image_suffix_search__inject':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:66:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   66 |     def _inject(iterator=iterator, suffix=suffix):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:64:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   64 |     if suffix is None:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py: In function 'dyld_image_suffix_search_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:73:3: error: too few arguments to function 'dyld_image_suffix_search__inject'; expected 2, have 0
   73 |     return _inject()
      |   ^ ~~~~~~~~~~~~~~~~              
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:62:15: note: declared here
   62 |     """For a potential path iterator, add DYLD_IMAGE_SUFFIX semantics"""
      |               ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:73:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   73 |     return _inject()
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py: In function 'dyld_override_search_0335d0':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:108:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
  108 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:107:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
  107 |             yield os.path.join(path, framework['name'])
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py:91:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   91 | 
      |           ^   
... (100 more lines)
```

Exit code: 1
Elapsed: 9.72s
