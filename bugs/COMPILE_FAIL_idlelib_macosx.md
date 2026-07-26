# COMPILE_FAIL: Lib/idlelib/macosx.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:48:11: warning: unused variable '_tag' [-Wunused-variable]
   48 |         _tk_type = "other"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:53:11: warning: unused variable '_tag' [-Wunused-variable]
   53 |     Returns True if IDLE is using a native OS X Tk (Cocoa or Carbon).
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:58:11: warning: unused variable '_tag' [-Wunused-variable]
   58 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |         _init_tk_type()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:82:13: warning: unused variable '_tag' [-Wunused-variable]
   82 |     return _tk_type == "xquartz"
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py: In function '_init_tk_type':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:353:11: warning: variable '_t74' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:343:11: warning: variable '_t64' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:342:10: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:341:10: warning: variable '_t62' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:338:11: warning: variable '_t59' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:333:10: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:325:10: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:319:10: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:318:11: warning: variable 'ws' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:316:10: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:313:11: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:295:10: warning: unused variable '_t18' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:278:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  278 |     main('idlelib.idle_test.test_macosx', verbosity=2)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py: In function 'isAquaTk':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:54:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   54 |     """
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py: In function 'isCarbonTk':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:62:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   62 |     newer Cocoa Aqua Tk).
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py: In function 'isCocoaTk':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py:71:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   71 |     """
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/macosx.py: In function 'isXQuartz':
... (385 more lines)
```

Exit code: 1
Elapsed: 11.03s
