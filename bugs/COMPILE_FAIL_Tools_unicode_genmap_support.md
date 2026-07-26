# COMPILE_FAIL: Tools/unicode/genmap_support.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/unicode/genmap_support.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_DecodeMapWriter_filler_class", referenced from:
      _DecodeMapWriter___init__ in genmap_support.o
  "_EncodeMapWriter_filler_class", referenced from:
      _EncodeMapWriter___init__ in genmap_support.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 14.15s
