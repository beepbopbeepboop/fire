# COMPILE_FAIL: Lib/test/test_type_params.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:381:11: warning: unused variable '_tag' [-Wunused-variable]
  381 |             def meth(self):
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:386:11: warning: unused variable '_tag' [-Wunused-variable]
  386 |             # __class__ and __classdict__
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:391:11: warning: unused variable '_tag' [-Wunused-variable]
  391 |         self.assertEqual(c.meth(1), "basechild")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:406:11: warning: unused variable '_tag' [-Wunused-variable]
  406 |         self.assertEqual(func(), (int, "outer", T))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:415:13: warning: unused variable '_tag' [-Wunused-variable]
  415 |         type Alias[T: [lambda: T for T in (T, [1])[1]]] = [lambda: T for T in T.__name__]
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py: In function 'TypeParamsInvalidTest_test_name_collisions':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:854:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  854 |                 return __foo
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:852:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  852 |                 __foo = 1
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:851:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  851 |                 _X_foo = 2
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:850:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  850 |                 class X[T]: pass
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:849:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  849 |             def f():
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:848:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  848 |         ns = run_code("""
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:847:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  847 |     def test_no_leaky_mangling_in_function(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:846:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  846 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:845:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  845 |         self.assertEqual(ns["__after"], "after")
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_params.py:844:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
... (10941 more lines)
```

Exit code: 1
Elapsed: 15.02s
