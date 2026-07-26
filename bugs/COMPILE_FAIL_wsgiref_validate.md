# COMPILE_FAIL: Lib/wsgiref/validate.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py: In function '_alloc_ErrorWrapper':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:86:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   86 |   - That .close() is not called
      | ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py: In function '_alloc_InputWrapper':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:100:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  100 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py: In function '_alloc_IteratorWrapper':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:114:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  114 | import re
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py: In function '_alloc_WriteWrapper':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:128:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  128 |         raise AssertionError(*args)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py: In function '_alloc_validator_lint_app_start_response_wrapper_env':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:145:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  145 |     at that point).
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py: In function 'validator_lint_app_start_response_wrapper':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:198:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  198 |         v = self.input.read(*args)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:194:7: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
  194 |         self.input = wsgi_input
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py: In function '_alloc_validator_lint_app_env':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:184:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  184 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py: In function 'validator_lint_app':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:275:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  275 |         if type(v) is not bytes:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:217:11: warning: variable 'start_response' set but not used [-Wunused-but-set-variable]
  217 |         while line := self.readline():
      |           ^~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py: In function 'validator_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:192:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  192 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py: In function 'InputWrapper___init__':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:196:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  196 |     def read(self, *args):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/validate.py:194:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  194 |         self.input = wsgi_input
      |           ^~~
... (806 more lines)
```

Exit code: 1
Elapsed: 13.54s
