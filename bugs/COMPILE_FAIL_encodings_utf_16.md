# COMPILE_FAIL: Lib/encodings/utf_16.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/encodings/utf_16.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_IncrementalDecoder_decoder", referenced from:
      _IncrementalDecoder__buffer_decode in utf_16.o
  "_IncrementalEncoder_encoder", referenced from:
      _IncrementalEncoder_encode in utf_16.o
  "_StreamWriter_encoder", referenced from:
      _StreamWriter_encode in utf_16.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 11.60s
