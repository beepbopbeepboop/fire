# COMPILE_FAIL: Modules/_decimal/tests/bignum.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:49:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:59:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:74:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:83:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py: In function 'xhash_907e1e':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:26:9: error: too many arguments to function 'pow'; expected 2, have 3
   26 |         exp_hash = pow(10, exp, _PyHASH_MODULUS)
      |         ^~~            ~~~
In file included from bignum.ci:7:
/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/math.h:453:15: note: declared here
  453 | extern double pow(double, double);
      |               ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:28:10: error: too many arguments to function 'pow'; expected 2, have 3
   28 |         exp_hash = pow(_PyHASH_10INV, -exp, _PyHASH_MODULUS)
      |          ^~~              ~~~~
/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/math.h:453:15: note: declared here
  453 | extern double pow(double, double);
      |               ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:18:10: error: too many arguments to function 'pow'; expected 2, have 3
   18 | _PyHASH_10INV = pow(10, _PyHASH_MODULUS - 2, _PyHASH_MODULUS)
      |          ^~~              ~~~~
/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/math.h:453:15: note: declared here
  453 | extern double pow(double, double);
      |               ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py: At top level:
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:62:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:101:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:72:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:63:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:58:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Modules/_decimal/tests/bignum.py:53:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
bignum.ci:458:16: warning: 'id' defined but not used [-Wunused-function]
  458 | static int64_t id (int64_t x) { return x; }
      |                ^~
bignum.ci:457:19: warning: '_Bool_items' defined but not used [-Wunused-function]
  457 | static MojoList * _Bool_items (int64_t a) { return mojo_list_new(); }
      |                   ^~~~~~~~~~~
bignum.ci:456:15: warning: '_ReflectTable_in_dll' defined but not used [-Wunused-function]
  456 | static char * _ReflectTable_in_dll (int64_t a, int64_t b, char * c) { return (char *)dlsym((void *)b, c); }
      |               ^~~~~~~~~~~~~~~~~~~~
In file included from bignum.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:396:12: warning: '_mojo_vprintf' defined but not used [-Wunused-function]
... (9 more lines)
```

Exit code: 1
Elapsed: 13.82s
