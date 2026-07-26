# COMPILE_FAIL: Lib/email/base64mime.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:55:11: warning: unused variable '_tag' [-Wunused-variable]
   55 |         n += 4
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:60:11: warning: unused variable '_tag' [-Wunused-variable]
   60 |     """Encode a single header line with Base64 encoding in a given charset.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:65:11: warning: unused variable '_tag' [-Wunused-variable]
   65 |     if not header_bytes:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:80:11: warning: unused variable '_tag' [-Wunused-variable]
   80 |     this to "\r\n" if you will be using the result of this function directly
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:89:13: warning: unused variable '_tag' [-Wunused-variable]
   89 |         # BAW: should encode() inherit b2a_base64()'s dubious behavior in
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py: In function 'header_length_fa7153':
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:183:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:179:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:174:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py: In function 'header_encode_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:70:15: error: invalid operands to binary % (have 'char *' and 'MojoList *')
   70 |     return '=?%s?b?%s?=' % (charset, encoded)
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:79:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
   79 |     Each line of encoded text will end with eol, which defaults to "\n".  Set
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:61:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   61 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py: In function 'body_encode_06e87d':
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:130:7: warning: variable '_t52' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:124:7: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:108:10: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
  108 |         return a2b_base64(string.encode('raw-unicode-escape'))
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:100:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
  100 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:75:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   75 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py: In function 'decode_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/email/base64mime.py:111:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  111 | 
... (49 more lines)
```

Exit code: 1
Elapsed: 57.71s
