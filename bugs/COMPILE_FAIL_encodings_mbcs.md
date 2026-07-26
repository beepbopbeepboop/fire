# COMPILE_FAIL: Lib/encodings/mbcs.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/encodings/mbcs.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_mbcs_decode", referenced from:
      _decode_1ce6ce in mbcs.o
  "_mbcs_encode", referenced from:
      _IncrementalEncoder_encode in mbcs.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.99s
