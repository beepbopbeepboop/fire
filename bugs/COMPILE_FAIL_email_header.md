# COMPILE_FAIL: Lib/email/header.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/header.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "__Accumulator_append", referenced from:
      __ValueFormatter_newline in header.o
      __ValueFormatter_add_transition in header.o
      _Header_encode in header.o
      __ValueFormatter__append_chunk in header.o
      __Accumulator_push in header.o
  "_bytes", referenced from:
      _decode_header_0c85c9 in header.o
  "_super", referenced from:
      __ValueFormatter___init__ in header.o
      __ValueFormatter_newline in header.o
      __ValueFormatter_newline in header.o
      _Header_encode in header.o
      __Accumulator___init__ in header.o
      __Accumulator_pop in header.o
      __Accumulator_pop in header.o
      ...
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 13.73s
