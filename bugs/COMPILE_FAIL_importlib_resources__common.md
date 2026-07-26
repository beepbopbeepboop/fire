# COMPILE_FAIL: Lib/importlib/resources/_common.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 |     # zipimport.zipimporter does not support weak references, resulting in a
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:71:11: warning: unused variable '_tag' [-Wunused-variable]
   71 |         return None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:76:11: warning: unused variable '_tag' [-Wunused-variable]
   76 | def resolve(cand: Optional[Anchor]) -> types.ModuleType:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:91:11: warning: unused variable '_tag' [-Wunused-variable]
   91 |     """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:100:13: warning: unused variable '_tag' [-Wunused-variable]
  100 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function '_alloc_package_to_anchor_wrapper_env':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:229:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py: In function 'package_to_anchor_wrapper':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:51:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   51 | @package_to_anchor
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:48:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   48 |     return wrapper
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:40:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   40 |                 DeprecationWarning,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:273:1: warning: label 'bb_6' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:46:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   46 |         return func(anchor)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:268:1: warning: label 'bb_3' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:263:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:261:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:260:10: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:259:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:258:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:257:10: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:256:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:255:9: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:254:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:253:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:252:10: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_common.py:251:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
... (261 more lines)
```

Exit code: 1
Elapsed: 10.39s
