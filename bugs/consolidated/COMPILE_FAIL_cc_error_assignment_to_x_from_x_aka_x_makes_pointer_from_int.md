# COMPILE_FAIL: CC ERROR: assignment to 'X' from 'X' {aka 'X'} makes pointer from integer without a cast [-Wint-conversion]

**2 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:57:11: warning: unused variable '_tag' [-Wunused-variable]
   57 | # always available algorithm is added.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:62:11: warning: unused variable '_tag' [-Wunused-variable]
   62 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:67:11: warning: unused variable '_tag' [-Wunused-variable]
   67 | __all__ = __always_supported + ('new', 'algorithms_guaranteed',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:82:11: warning: unused variable '_tag' [-Wunused-variable]
   82 | def __get_builtin_constructor(name):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:91:13: warning: unused variable '_tag' [-Wunused-variable]
   91 |         elif name in {'MD5', 'md5'}:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py: In function '__get_builtin_constructor_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/hashlib.py:226:10: warning: unused variable '_t15' [-Wunused-variable]
  226 |         )
      |          ^   
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
/U
```

## Affected files

- `Lib/hashlib.py`
- `Lib/hmac.py`
