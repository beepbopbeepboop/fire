# COMPILE_FAIL: Lib/importlib/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:33:11: warning: unused variable '_tag' [-Wunused-variable]
   33 | try:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:38:11: warning: unused variable '_tag' [-Wunused-variable]
   38 |     _bootstrap._bootstrap_external = _bootstrap_external
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:43:11: warning: unused variable '_tag' [-Wunused-variable]
   43 |         _bootstrap_external.__file__ = __file__.replace('__init__.py', '_bootstrap_external.py')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:58:11: warning: unused variable '_tag' [-Wunused-variable]
   58 | # Public API #########################################################
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:67:13: warning: unused variable '_tag' [-Wunused-variable]
   67 |         if hasattr(finder, 'invalidate_caches'):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py: In function 'invalidate_caches':
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:175:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:172:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py: In function 'import_module_d4d5c5':
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:88:23: error: 'struct _root_toplev' has no member named '_bootstrap'
   88 |     return _bootstrap._gcd_import(name[level:], package, level)
      |                       ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:104:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
  104 |             name = module.__name__
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:76:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   76 |     relative import to an absolute import.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py: In function 'reload_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:126:24: error: 'struct _root_toplev' has no member named '_bootstrap'
  126 |         spec = module.__spec__ = _bootstrap._find_spec(name, pkgpath, target)
      |                        ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:126:9: error: request for member '__spec__' in something not a structure or union
  126 |         spec = module.__spec__ = _bootstrap._find_spec(name, pkgpath, target)
      |         ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:129:24: error: 'struct _root_toplev' has no member named '_bootstrap'
  129 |         _bootstrap._exec(spec, module)
      |                        ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:150:1: warning: label 'bb_21' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:244:11: warning: variable '_t146' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:239:11: warning: variable '_t141' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:238:10: warning: unused variable '_t140' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:224:11: warning: variable '_t126' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/__init__.py:223:11: warning: variable '_t125' set but not used [-Wunused-but-set-variable]
... (70 more lines)
```

Exit code: 1
Elapsed: 10.17s
