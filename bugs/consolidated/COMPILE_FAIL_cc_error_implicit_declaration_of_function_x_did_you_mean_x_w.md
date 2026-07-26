# COMPILE_FAIL: CC ERROR: implicit declaration of function 'X'; did you mean 'X'? [-Wimplicit-function-declaration]

**7 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py: In function '_alloc_AsParamWrapper':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:211:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  211 |                     c_type.from_param(a)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py: In function '_alloc_POINT':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:225:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  225 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py: In function 'BasicWrapTestCase_wrap':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:457:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py: In function 'BasicWrapTestCase_test_wchar_parm':
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:72:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   72 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:70:11: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
   70 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:69:10: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
   69 |             return v
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:68:7: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
   68 |             args.append(v)
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:67:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
   67 |         def callback(v):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:66:11: warning: variable 'result' set but not used [-Wunused-but-set-variable]
   66 | 
      |           ^     
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:65:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
   65 |                     1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1]
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:64:10: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
   64 |         expected = [262144, 131072, 65536, 32768, 16384, 8192, 4096, 2048,
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:63:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
   63 |         args = []
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:62:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   62 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:61:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
   61 |         f = dll._testfunc_callback_i_if
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:60:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
   60 |     def test_shorts(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:59:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
   59 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:58:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
   58 |         self.assertEqual(result.contents.value, 99)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_as_parameter.py:57:11: warning: variable '_t25' set but not used [-Wunused-but
```

## Affected files

- `Lib/test/test_ctypes/test_as_parameter.py`
- `Lib/test/test_ctypes/test_functions.py`
- `Lib/test/test_ctypes/test_incomplete.py`
- `Lib/test/test_ctypes/test_keeprefs.py`
- `Lib/test/test_ctypes/test_pointers.py`
- `Lib/turtledemo/minimal_hanoi.py`
- `Lib/turtledemo/sorting_animate.py`
