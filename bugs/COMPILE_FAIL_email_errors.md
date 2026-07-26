# COMPILE_FAIL: Lib/email/errors.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/errors.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_super", referenced from:
      _MessageDefect___init__ in errors.o
      _NoBoundaryInMultipartDefect___init__ in errors.o
      _StartBoundaryNotFoundDefect___init__ in errors.o
      _CloseBoundaryNotFoundDefect___init__ in errors.o
      _FirstHeaderLineIsContinuationDefect___init__ in errors.o
      _MisplacedEnvelopeHeaderDefect___init__ in errors.o
      _MissingHeaderBodySeparatorDefect___init__ in errors.o
      ...
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 36.48s
