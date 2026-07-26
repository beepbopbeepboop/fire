# COMPILE_FAIL: PC/validate_ucrtbase.py

Source file: `/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
   56 |         sys.exit(2)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:61:11: warning: unused variable '_tag' [-Wunused-variable]
   61 |     sys.exit(2)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 |     print('Failed to get version info.')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:81:11: warning: unused variable '_tag' [-Wunused-variable]
   81 | print('{} is version {}.{}.{}.{}'.format(name.value, *ver))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:90:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:50:3: error: 'name_len' undeclared (first use in this function)
   50 |     name_len *= 2
      |   ^ ~~~~~~
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:50:3: note: each undeclared identifier is reported only once for each function it appears in
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:336:11: warning: variable '_t169' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:335:11: warning: variable '_t168' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:315:11: warning: variable '_t148' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:314:11: warning: variable '_t147' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:313:11: warning: variable '_t146' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:312:11: warning: variable '_t145' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:271:11: warning: variable '_t104' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:270:11: warning: variable '_t103' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:263:11: warning: variable '_t96' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:261:11: warning: variable '_t94' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:259:10: warning: variable '_t92' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:258:11: warning: variable '_t91' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:255:11: warning: variable '_t88' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:254:11: warning: variable '_t87' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:243:11: warning: variable '_t76' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:242:11: warning: variable '_t75' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:241:11: warning: variable '_t74' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:237:11: warning: variable '_t70' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:236:11: warning: variable '_t69' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:228:11: warning: variable '_t61' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:226:11: warning: variable '_t59' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:225:11: warning: variable '_t58' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:217:11: warning: variable '_t51' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:214:11: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:200:11: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/PC/validate_ucrtbase.py:199:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
... (39 more lines)
```

Exit code: 1
Elapsed: 13.33s
