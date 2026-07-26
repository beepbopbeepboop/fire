# COMPILE_FAIL: Lib/encodings/punycode.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:60:11: warning: unused variable '_tag' [-Wunused-variable]
   60 |             if index == -1:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:65:11: warning: unused variable '_tag' [-Wunused-variable]
   65 |             delta = 0
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:70:11: warning: unused variable '_tag' [-Wunused-variable]
   70 | def T(j, bias):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:85:11: warning: unused variable '_tag' [-Wunused-variable]
   85 |             result.append(digits[N])
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:94:13: warning: unused variable '_tag' [-Wunused-variable]
   94 |     else:
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py: In function 'segregate_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:215:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  215 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py: In function 'selective_len_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:25:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   25 |     for c in str:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py: In function 'selective_find_039fbf':
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:33:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   33 |     only ordinals up to and including char, and pos is the position in
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py: In function 'insertion_unsort_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:62:11: warning: variable 'oldindex' set but not used [-Wunused-but-set-variable]
   62 |             delta += index - oldindex
      |           ^ ~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:58:11: warning: variable 'oldchar' set but not used [-Wunused-but-set-variable]
   58 |         while 1:
      |           ^~~~~~ 
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:57:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   57 |         delta = (curlen+1) * (char - oldchar)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py: In function 'generate_generalized_integer_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:113:7: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
  113 |         result.extend(s)
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/punycode.py:98:7: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
   98 |     divisions = 0
      |       ^~~~
... (134 more lines)
```

Exit code: 1
Elapsed: 10.14s
