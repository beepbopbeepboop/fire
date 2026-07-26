# COMPILE_FAIL: Tools/build/generate_token.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 |                 string_to_tok[string] = value
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:46:11: warning: unused variable '_tag' [-Wunused-variable]
   46 | def update_file(file, content):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:51:11: warning: unused variable '_tag' [-Wunused-variable]
   51 |     except (OSError, ValueError):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 | #ifdef __cplusplus
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:75:13: warning: unused variable '_tag' [-Wunused-variable]
   75 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py: In function 'load_tokens_584a43':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:212:11: warning: variable 'fp' set but not used [-Wunused-but-set-variable]
  212 |    :header-rows: 1
      |           ^~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py: In function 'update_file_0335d0':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:79:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
   79 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:53:10: warning: unused variable '_t6' [-Wunused-variable]
   53 |     with open(file, 'w') as fobj:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py: In function 'make_h_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:134:15: error: invalid operands to binary % (have 'char *' and 'MojoList *')
  134 | 
      |               ^
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:104:7: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
  104 | """
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:75:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   75 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:71:11: warning: variable 'string_to_tok' set but not used [-Wunused-but-set-variable]
   71 | #  error "this header requires Py_BUILD_CORE define"
      |           ^~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py: In function 'generate_chars_to_token_d4d5c5':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:186:10: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
  186 |         m = chars_to_token.setdefault(len(string), {})
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_token.py:183:10: warning: variable '_t53' set but not used [-Wunused-but-set-variable]
... (147 more lines)
```

Exit code: 1
Elapsed: 13.89s
