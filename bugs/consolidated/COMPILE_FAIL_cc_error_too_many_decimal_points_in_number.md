# COMPILE_FAIL: CC ERROR: too many decimal points in number

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:75:11: warning: unused variable '_tag' [-Wunused-variable]
   75 |                 self.i = imag
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:80:11: warning: unused variable '_tag' [-Wunused-variable]
   80 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:85:11: warning: unused variable '_tag' [-Wunused-variable]
   85 |             def __add__(self, other):
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:100:11: warning: unused variable '_tag' [-Wunused-variable]
  100 |         # test __bool__
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:109:13: warning: unused variable '_tag' [-Wunused-variable]
  109 |         # test __rsub__
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py: In function 'concretize_not_implemented':
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:189:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  189 |         # test __float__
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py: In function 'concretize_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:237:11: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:236:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:208:10: warning: unused variable '_t12' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py: In function 'TestNumbers_test_int':
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:89:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   89 |                 raise NotImplementedError
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:87:11: warning: variable '_t61' set but not used [-Wunused-but-set-variable]
   87 |                     return MyComplex(self.imag + other.imag,
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:86:10: warning: variable '_t60' set but not used [-Wunused-but-set-variable]
   86 |                 if isinstance(other, Complex):
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:85:11: warning: variable '_t59' set but not used [-Wunused-but-set-variable]
   85 |             def __add__(self, other):
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:84:10: warning: variable '_t58' set but not used [-Wunused-but-set-variable]
   84 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:83:11: warning: variable '_t57' set but not used [-Wunused-but-set-variable]
   83 |                 return self.i
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:82:10: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
   82 |             def imag(self):
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_abstract_numbers.py:81:10: warning: variable '_t55' set but not used [-Wunused-but-set-variable]
   81 |             @property
      |          ^  ~
/Users/mrs/net/Pyth
```

## Affected files

- `Lib/test/test_abstract_numbers.py`
