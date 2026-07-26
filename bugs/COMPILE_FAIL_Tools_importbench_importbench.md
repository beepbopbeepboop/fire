# COMPILE_FAIL: Tools/importbench/importbench.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:89:11: warning: unused variable '_tag' [-Wunused-variable]
   89 |             yield from bench(name, lambda: sys.modules.pop(name),
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:94:11: warning: unused variable '_tag' [-Wunused-variable]
   94 |     benchmark_wo_bytecode.__doc__ = benchmark_wo_bytecode.__doc__.format(name)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:99:11: warning: unused variable '_tag' [-Wunused-variable]
   99 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:114:11: warning: unused variable '_tag' [-Wunused-variable]
  114 |             assert not os.path.exists(cache_from_source(mapping[name]))
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:123:13: warning: unused variable '_tag' [-Wunused-variable]
  123 |         def cleanup():
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py: In function 'bench_7a6366':
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:33:1: warning: label 'bb_13' defined but not used [-Wunused-label]
   33 |                 cleanup()
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:311:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:310:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:305:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:303:10: warning: unused variable '_t18' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:286:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:281:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py: In function 'from_cache_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:91:11: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
   91 |         finally:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:83:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
   83 |         """Source w/o bytecode: {}"""
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:78:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
   78 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:57:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   57 |     # Relying on built-in importer being implicit.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:53:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   53 |     """Built-in module"""
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py: In function 'builtin_mod_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py:75:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
   75 |                              seconds=seconds)
... (478 more lines)
```

Exit code: 1
Elapsed: 13.88s
