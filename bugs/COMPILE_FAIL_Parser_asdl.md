# COMPILE_FAIL: Parser/asdl.py

Source file: `/Users/mrs/net/Python-3.14.6/Parser/asdl.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_namedtuple", referenced from:
      __toplevel in asdl.o
  "_next", referenced from:
      _ASDLParser__advance in asdl.o
  "_super", referenced from:
      _Check___init__ in asdl.o
      _check_0c85c9 in asdl.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 15.65s
