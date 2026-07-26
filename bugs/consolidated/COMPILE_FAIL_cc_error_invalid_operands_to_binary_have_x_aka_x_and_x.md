# COMPILE_FAIL: CC ERROR: invalid operands to binary % (have 'X' {aka 'X'} and 'X')

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:45:11: warning: unused variable '_tag' [-Wunused-variable]
   45 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
   50 |     Unlike most other Unix platforms, Mac OS X embeds absolute paths
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:55:11: warning: unused variable '_tag' [-Wunused-variable]
   55 |     if os.name == "nt":
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:70:11: warning: unused variable '_tag' [-Wunused-variable]
   70 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:79:13: warning: unused variable '_tag' [-Wunused-variable]
   79 | ) -> pathlib.Path:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py: In function 'get_extra_flags_abb124':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:271:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  271 |             (token,) = pieces
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:264:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  264 |         if not line or line.startswith("#"):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py: In function 'fixup_build_ext_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:70:1: warning: label 'bb_17' defined but not used [-Wunused-label]
   70 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:122:10: warning: variable '_t84' set but not used [-Wunused-but-set-variable]
  122 |                 extra_link_args.append("-fno-lto")
      |          ^   
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:114:11: warning: variable '_t77' set but not used [-Wunused-but-set-variable]
  114 |         extra_compile_args.append("-UNDEBUG")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:113:11: warning: variable 'equals' set but not used [-Wunused-but-set-variable]
  113 |     if keep_asserts:
      |           ^~~~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:110:11: warning: variable '_t74' set but not used [-Wunused-but-set-variable]
  110 |     if sys.platform == "win32" and sysconfig.get_config_var("Py_GIL_DISABLED"):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:109:11: warning: variable 'name' set but not used [-Wunused-but-set-variable]
  109 |     extra_compile_args.append("-D_Py_TEST_PEGEN")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:106:11: warning: variable '_t71' set but not used [-Wunused-but-set-variable]
  106 |     extra_compile_args = get_extra_flags("CFLAGS", "PY_CFLAGS_NODIST")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:102:11: warning: variable '_t67' set but not used [-Wunused-but-set-variable]
  102 |         setuptools.logging.set_threshold(logging.DEBUG)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/build.py:67:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
   
```

## Affected files

- `Tools/peg_generator/pegen/build.py`
