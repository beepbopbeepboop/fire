# COMPILE_FAIL: Lib/ctypes/wintypes.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:250:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:255:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:260:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:275:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:284:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py: In function 'VARIANT_BOOL___repr__':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:23:13: error: invalid operands to binary % (have 'char *' and 'MojoList *')
   23 |         return "%s(%r)" % (self.__class__.__name__, self.value)
      |             ^
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:367:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:361:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:355:11: warning: variable '_t198' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:352:11: warning: variable '_t195' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:349:11: warning: variable '_t192' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:346:11: warning: variable '_t189' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:343:11: warning: variable '_t186' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:340:11: warning: variable '_t183' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:337:11: warning: variable '_t180' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:334:11: warning: variable '_t177' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:331:11: warning: variable '_t174' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:328:11: warning: variable '_t171' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:325:11: warning: variable '_t168' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:322:11: warning: variable '_t165' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:319:11: warning: variable '_t162' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:316:11: warning: variable '_t159' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:313:11: warning: variable '_t156' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:310:11: warning: variable '_t153' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:245:11: warning: variable '_t88' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:239:11: warning: variable '_t82' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:235:11: warning: variable 'LPARAM' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:230:11: warning: variable 'WPARAM' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:222:11: warning: variable '_t67' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:216:11: warning: variable '_t61' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:226:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:302:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:273:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:264:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:259:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/ctypes/wintypes.py:254:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
wintypes.ci:458:16: warning: 'id' defined but not used [-Wunused-function]
  458 | static int64_t id (int64_t x) { return x; }
      |                ^~
... (17 more lines)
```

Exit code: 1
Elapsed: 9.31s
