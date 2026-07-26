# COMPILE_FAIL: Lib/sysconfig/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:75:11: warning: unused variable '_tag' [-Wunused-variable]
   75 |     # Special care is needed to ensure that variable expansion works, even
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:80:11: warning: unused variable '_tag' [-Wunused-variable]
   80 |         for name in tuple(variables):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:85:11: warning: unused variable '_tag' [-Wunused-variable]
   85 |                 m = m1 if m1.start() < m2.start() else m2
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:100:11: warning: unused variable '_tag' [-Wunused-variable]
  100 |                 elif n in renamed_variables:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:109:13: warning: unused variable '_tag' [-Wunused-variable]
  109 |                         item = str(done['PY_' + n])
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py: In function '_parse_makefile_89c6a7':
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:611:7: warning: variable '_t350' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:580:7: warning: variable '_t320' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:545:10: warning: variable '_t285' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:541:7: warning: variable '_t281' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:518:11: warning: variable '_t258' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:517:10: warning: unused variable '_t257' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:506:10: warning: variable '_t246' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:494:11: warning: variable '_t234' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:454:10: warning: variable '_t195' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:434:11: warning: variable '_t175' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:420:11: warning: variable '_t163' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:394:11: warning: variable '_t138' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:387:11: warning: variable '_t132' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:348:10: warning: variable '_t97' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:346:10: warning: variable '_t95' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:335:11: warning: variable '_t84' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:334:10: warning: unused variable '_t83' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:325:10: warning: variable '_t74' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:324:10: warning: variable 'tmpv' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:313:10: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:311:10: warning: variable '_t61' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:305:11: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:300:11: warning: variable '_t52' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:298:11: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:290:11: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/sysconfig/__main__.py:269:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  269 |     _print_dict('Variables', get_config_vars())
      |          ^~~~
... (83 more lines)
```

Exit code: 1
Elapsed: 89.33s
