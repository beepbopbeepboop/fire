# COMPILE_FAIL: Lib/test/test_type_aliases.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:223:11: warning: unused variable '_tag' [-Wunused-variable]
  223 |         self.assertEqual(TA.__module__, __name__)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:228:11: warning: unused variable '_tag' [-Wunused-variable]
  228 |             TA[int]
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:233:11: warning: unused variable '_tag' [-Wunused-variable]
  233 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:248:11: warning: unused variable '_tag' [-Wunused-variable]
  248 |         msg = "follows default type parameter"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:257:13: warning: unused variable '_tag' [-Wunused-variable]
  257 |                     TypeAliasType("A", int, type_params=type_params)
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py: In function 'TypeParamsInvalidTest_test_name_collisions':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:423:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:421:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:420:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:419:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:418:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:417:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:416:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py: In function 'TypeParamsInvalidTest_test_name_non_collision_02':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:60:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   60 |         cls = ns["Outer"]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:58:11: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
   58 |             """
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:57:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
   57 |                     return TA1
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:56:11: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
   56 |                     type TA1[C] = TA1[A, B] | int
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:55:10: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
   55 |                 def inner[B](self):
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:54:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
   54 |             class Outer[A]:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_aliases.py:53:10: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
   53 |         ns = run_code("""
... (4681 more lines)
```

Exit code: 1
Elapsed: 15.24s
