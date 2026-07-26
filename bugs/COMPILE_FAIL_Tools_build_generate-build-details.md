# COMPILE_FAIL: Tools/build/generate-build-details.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:42:11: warning: unused variable '_tag' [-Wunused-variable]
   42 |         lambda: collections.defaultdict(dict),
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:47:11: warning: unused variable '_tag' [-Wunused-variable]
   47 |     data['base_prefix'] = sysconfig.get_config_var('installed_base')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 |     )
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:67:11: warning: unused variable '_tag' [-Wunused-variable]
   67 |     data['suffixes']['bytecode'] = importlib.machinery.BYTECODE_SUFFIXES
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:76:13: warning: unused variable '_tag' [-Wunused-variable]
   76 |     LIBPYTHON = sysconfig.get_config_var('LIBPYTHON')
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py: In function 'get_dict_key_800bbe':
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:28:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   28 |         container = container[part]
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py: In function 'generate_data_584a43':
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:365:11: warning: variable '_t322' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:345:11: warning: variable '_t302' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:313:11: warning: variable '_t271' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:294:11: warning: variable '_t254' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:287:11: warning: variable '_t248' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:280:11: warning: variable '_t242' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:273:11: warning: variable '_t236' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:266:11: warning: variable '_t230' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:259:11: warning: variable '_t224' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:252:11: warning: variable '_t218' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:167:11: warning: variable '_t133' set but not used [-Wunused-but-set-variable]
  167 | 
      |           ^    
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:162:11: warning: variable '_t128' set but not used [-Wunused-but-set-variable]
  162 |         new_path = relative_path(current_path, base_prefix)
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:155:10: warning: variable '_t121' set but not used [-Wunused-but-set-variable]
  155 |                 container = container[part]
      |          ^    
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:75:11: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
   75 |     PY3LIBRARY = sysconfig.get_config_var('PY3LIBRARY')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate-build-details.py:68:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
   68 |     #data['suffixes']['optimized_bytecode'] = importlib.machinery.OPTIMIZED_BYTECODE_SUFFIXES
... (132 more lines)
```

Exit code: 1
Elapsed: 14.22s
