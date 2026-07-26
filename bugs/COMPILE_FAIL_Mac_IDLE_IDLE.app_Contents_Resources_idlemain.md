# COMPILE_FAIL: Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py

Source file: `/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:31:11: warning: unused variable '_tag' [-Wunused-variable]
   31 | # 2. IDLE script exports
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:36:11: warning: unused variable '_tag' [-Wunused-variable]
   36 | #       This is the magic step.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 | #  generated automatically by bundlebuilder in the Python 2.x build.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
   56 |     sys.path = [value for value in sys.path if
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:65:13: warning: unused variable '_tag' [-Wunused-variable]
   65 | for idx, value in enumerate(sys.argv):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:202:10: warning: variable '_t72' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:199:11: warning: variable '_t69' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:193:10: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:183:11: warning: variable '_t55' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:175:11: warning: variable '_t47' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:166:10: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:155:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:136:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:133:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:129:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py: At top level:
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:79:5: error: conflicting types for '_gimple_main'; have 'int(void)'
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:11:9: note: previous declaration of '_gimple_main' with type 'int64_t()' {aka 'long long int()'}
   11 | # Make sure sys.executable points to the python interpreter inside the
      |         ^~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:95:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:83:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:54:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
   54 | p = pyex.partition('.app')
      |               ^~~~~~~~~~~~       
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:45:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
   45 | # Now fix up the execution environment before importing idlelib.
      |            ^~~~~~~~~~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Mac/IDLE/IDLE.app/Contents/Resources/idlemain.py:40:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
   40 | # (Note that the IDLE script and the setting of PYTHONEXECUTABLE is
      |                   ^~~~~~~~~~~~~~~~~~~~~
idlemain.ci:458:16: warning: 'id' defined but not used [-Wunused-function]
  458 | static int64_t id (int64_t x) { return x; }
... (18 more lines)
```

Exit code: 1
Elapsed: 13.18s
