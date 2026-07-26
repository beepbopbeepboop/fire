# COMPILE_FAIL: Lib/importlib/metadata/_text.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_text.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_hash", referenced from:
      _FoldedCase___hash__ in _text.o
  "_super", referenced from:
      _FoldedCase___lt__ in _text.o
      _FoldedCase___gt__ in _text.o
      _FoldedCase___eq__ in _text.o
      _FoldedCase___ne__ in _text.o
      _FoldedCase___hash__ in _text.o
      _FoldedCase___contains__ in _text.o
      _FoldedCase_lower in _text.o
      ...
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.05s
