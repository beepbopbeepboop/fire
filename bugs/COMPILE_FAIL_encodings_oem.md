# COMPILE_FAIL: Lib/encodings/oem.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/encodings/oem.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_oem_decode", referenced from:
      _decode_1ce6ce in oem.o
  "_oem_encode", referenced from:
      _IncrementalEncoder_encode in oem.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.98s
