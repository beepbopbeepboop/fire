# COMPILE_FAIL: Modules/_decimal/libmpdec/literature/fnt.py

Source file: `/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py:43:11: warning: unused variable '_tag' [-Wunused-variable]
   43 | # result arrays to recover the result in the usual base RADIX
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py:48:11: warning: unused variable '_tag' [-Wunused-variable]
   48 | #                           Primitive roots
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py:53:11: warning: unused variable '_tag' [-Wunused-variable]
   53 | #
      |           ^   
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py:68:11: warning: unused variable '_tag' [-Wunused-variable]
   68 |         return False
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py:77:13: warning: unused variable '_tag' [-Wunused-variable]
   77 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py: In function 'prod_1ce6ce':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py:153:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  153 | # The primitive roots are correct:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py:151:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  151 | w = [5, 31, 13]
      |          ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py: In function 'is_primitive_root_7a6366':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py:68:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   68 |         return False
      |          ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py: In function 'ntt_0c5bb1':
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py:168:9: error: too many arguments to function 'pow'; expected 2, have 3
  168 |     d_prime = pow(d, (p-2), p) # inverse of d
      |         ^~~             ~
In file included from fnt.ci:7:
/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/math.h:453:15: note: declared here
  453 | extern double pow(double, double);
      |               ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py:171:10: error: too many arguments to function 'pow'; expected 2, have 3
  171 |     r = pow(w, xi, p)             # primitive root of the subfield
      |          ^~~              ~
/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/math.h:453:15: note: declared here
  453 | extern double pow(double, double);
      |               ^~~
/Users/mrs/net/Python-3.14.6/Modules/_decimal/libmpdec/literature/fnt.py:172:10: error: too many arguments to function 'pow'; expected 2, have 3
  172 |     r_prime = pow(w, (p-1-xi), p) # inverse of r
      |          ^~~              ~
/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/math.h:453:15: note: declared here
... (68 more lines)
```

Exit code: 1
Elapsed: 13.13s
