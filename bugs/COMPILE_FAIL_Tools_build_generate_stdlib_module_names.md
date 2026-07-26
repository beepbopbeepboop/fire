# COMPILE_FAIL: Tools/build/generate_stdlib_module_names.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
# ERROR: compiling imported module 'check_extension_modules' from /Users/mrs/net/Python-3.14.6/Tools/build/check_extension_modules.py: 120:1: Expected NAME got KW('enum')
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:39:11: warning: unused variable '_tag' [-Wunused-variable]
   39 |     '_testsinglephase',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:44:11: warning: unused variable '_tag' [-Wunused-variable]
   44 |     'xxlimited_35',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:49:11: warning: unused variable '_tag' [-Wunused-variable]
   49 |     'doctest',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:64:11: warning: unused variable '_tag' [-Wunused-variable]
   64 |         names.add(name)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:73:13: warning: unused variable '_tag' [-Wunused-variable]
   73 |         if not os.path.isdir(package_path):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py: In function 'list_builtin_modules_271e62':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:203:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py: In function 'list_python_modules_271e62':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:62:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   62 |             continue
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:61:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   61 |         if not filename.endswith(".py"):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py: In function 'list_packages_271e62':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:71:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   71 |             continue
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:70:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   70 |         if name in IGNORE:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py: In function 'list_modules_setup_extensions_271e62':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:83:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   83 |     checker = ModuleChecker()
      |       ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py: In function 'list_frozen_271e62':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:113:7: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
  113 |     list_python_modules(names)
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:103:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  103 |     if submodules:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_stdlib_module_names.py:92:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
... (51 more lines)
```

Exit code: 1
Elapsed: 13.76s
