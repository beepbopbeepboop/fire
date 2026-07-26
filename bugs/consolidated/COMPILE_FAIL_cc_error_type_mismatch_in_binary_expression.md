# COMPILE_FAIL: CC ERROR: type mismatch in binary expression

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:47:11: warning: unused variable '_tag' [-Wunused-variable]
   47 |     @bigaddrspacetest
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 |         finally:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:57:11: warning: unused variable '_tag' [-Wunused-variable]
   57 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |     def test_optimized_concat(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:81:13: warning: unused variable '_tag' [-Wunused-variable]
   81 |                 # this statement uses a fast path in ceval.c
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py: In function 'BytesTest_test_concat':
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:40:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   40 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:33:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   33 |     def test_optimized_concat(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:30:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   30 |             x = None
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:177:1: warning: label 'bb_3' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:37:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   37 |             with self.assertRaises(OverflowError) as cm:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:168:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:166:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:165:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:164:10: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:163:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:162:10: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:161:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:160:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:159:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:158:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:157:10: warning: variable 'x' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_bigaddrspace.py:156:10: warning: variable '_t11' set but not used [-Wunused-b
```

## Affected files

- `Lib/test/test_bigaddrspace.py`
