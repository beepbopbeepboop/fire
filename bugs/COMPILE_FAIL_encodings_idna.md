# COMPILE_FAIL: Lib/encodings/idna.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:62:11: warning: unused variable '_tag' [-Wunused-variable]
   62 |                                      "Violation of BIDI requirement 3")
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:67:11: warning: unused variable '_tag' [-Wunused-variable]
   67 |     try:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |     else:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:87:11: warning: unused variable '_tag' [-Wunused-variable]
   87 |     try:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:96:13: warning: unused variable '_tag' [-Wunused-variable]
   96 |             raise UnicodeEncodeError("idna", label, 0, 1, "label empty")
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py: In function 'nameprep_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:273:11: warning: variable '_t89' set but not used [-Wunused-but-set-variable]
  273 |     def _buffer_encode(self, input, errors, final):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:257:10: warning: variable '_t75' set but not used [-Wunused-but-set-variable]
  257 |             trailing_dot = ''
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:250:11: warning: variable '_t68' set but not used [-Wunused-but-set-variable]
  250 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:244:11: warning: variable '_t62' set but not used [-Wunused-but-set-variable]
  244 |         if ace_prefix not in input.lower():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:238:11: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
  238 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:232:11: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
  232 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:226:11: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
  226 |                     offset + exc.end,
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:220:11: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
  220 |             except (UnicodeEncodeError, UnicodeDecodeError) as exc:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:214:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
  214 |         for i, label in enumerate(labels):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/encodings/idna.py:208:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
... (459 more lines)
```

Exit code: 1
Elapsed: 9.68s
