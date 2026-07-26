# COMPILE_FAIL: Lib/encodings/uu_codec.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:53:11: warning: unused variable '_tag' [-Wunused-variable]
   53 |     while True:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:58:11: warning: unused variable '_tag' [-Wunused-variable]
   58 |             data = binascii.a2b_uu(s)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:63:11: warning: unused variable '_tag' [-Wunused-variable]
   63 |             #sys.stderr.write("Warning: %s\n" % str(v))
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:78:11: warning: unused variable '_tag' [-Wunused-variable]
   78 |     def encode(self, input, final=False):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:87:13: warning: unused variable '_tag' [-Wunused-variable]
   87 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py: In function 'uu_encode_7a6366':
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:28:15: error: invalid operands to binary % (have 'char *' and 'MojoList *')
   28 |     write(('begin %o %s\n' % (mode & 0o777, filename)).encode('ascii'))
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:247:10: warning: variable '_t69' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:243:11: warning: variable '_t65' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:242:11: warning: variable '_t64' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:234:10: warning: variable '_t57' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:233:10: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:232:10: warning: variable '_t55' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:214:10: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:212:10: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:197:10: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:195:10: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:191:11: warning: variable '_var_write' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py: In function 'uu_decode_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:126:11: warning: variable '_t80' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:125:11: warning: variable '_t79' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:108:10: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:100:11: warning: variable 'data' set but not used [-Wunused-but-set-variable]
  100 |         streamreader=StreamReader,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:98:11: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
   98 |         incrementalencoder=IncrementalEncoder,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:96:10: warning: unused variable '_t52' [-Wunused-variable]
   96 |         encode=uu_encode,
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/uu_codec.py:57:11: warning: variable '_var_write' set but not used [-Wunused-but-set-variable]
... (111 more lines)
```

Exit code: 1
Elapsed: 9.84s
