# COMPILE_FAIL: Tools/clinic/libclinic/clanguage.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
   56 |         if ({condition}) {{{{{errcheck}
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:61:11: warning: unused variable '_tag' [-Wunused-variable]
   61 |             }}}}
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 |         super().__init__(filename)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:81:11: warning: unused variable '_tag' [-Wunused-variable]
   81 |                     fail("You may specify at most one function per block.\nFound a block containing at least two:\n\t" + repr(function) + " and " + repr(o))
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:90:13: warning: unused variable '_tag' [-Wunused-variable]
   90 |         minversion: VersionTuple | None = None
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py: In function 'CLanguage___init__':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:51:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   51 |         #    warning {message}
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:49:7: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   49 |         #    pragma message ({message})
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:48:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   48 |         #  ifdef _MSC_VER
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:47:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   47 |         #elif PY_VERSION_HEX >= 0x{major:02x}{minor:02x}00A0
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:46:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   46 |         #  error {message}
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:45:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   45 |         #if PY_VERSION_HEX >= 0x{major:02x}{minor:02x}00C0
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:44:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   44 |         // Emit compiler warnings when we get to Python {major}.{minor}.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:43:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   43 |     COMPILER_DEPRECATION_WARNING_PROTOTYPE: Final[str] = r"""
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:42:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   42 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/clanguage.py:41:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
... (645 more lines)
```

Exit code: 1
Elapsed: 14.12s
