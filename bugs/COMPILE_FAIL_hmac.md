# COMPILE_FAIL: Lib/hmac.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/hmac.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py: In function '__get_builtin_constructor_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:138:10: warning: unused variable '_t15' [-Wunused-variable]
  138 |         # Use the C function directly (very fast)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py: In function '__get_openssl_constructor_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:146:1: warning: label 'bb_7' defined but not used [-Wunused-label]
  146 |     named algorithm; optionally initialized with data (which must be
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:142:10: warning: unused variable '_t12' [-Wunused-variable]
  142 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py: In function '__py_new_07077a':
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:151:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  151 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py: In function '__hash_new_07077a':
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:171:1: warning: label 'bb_7' defined but not used [-Wunused-label]
  171 |     new = __hash_new
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:169:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
  169 | try:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:167:10: warning: unused variable '_t14' [-Wunused-variable]
  167 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:154:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  154 |     optionally initialized with data (which must be a bytes-like object).
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py: In function 'file_digest_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:251:7: warning: variable '_t72' set but not used [-Wunused-but-set-variable]
  251 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:244:11: warning: variable '_t65' set but not used [-Wunused-but-set-variable]
  244 |     # try them all, some may not work due to the OpenSSL
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:232:11: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
  232 |     while True:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:200:7: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
  200 |     The function may bypass Python's I/O and use the file descriptor *fileno*
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:176:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  176 |     _hashlib = None
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py: In function '_hashlib_toplevel':
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:67:28: error: assignment to 'MojoList *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]
   67 | __all__ = __always_supported + ('new', 'algorithms_guaranteed',
      |                            ^
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:183:8: error: assignment to 'int64_t' {aka 'long long int'} from 'MojoList *' makes integer from pointer without a cast [-Wint-conversion]
... (1093 more lines)
```

Exit code: 1
Elapsed: 9.84s
