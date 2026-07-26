# COMPILE_FAIL: Lib/test/test_winconsoleio.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_winconsoleio.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_write_input", referenced from:
      _WindowsConsoleIOTests_assertStdinRoundTrip in test_winconsoleio.o
      _WindowsConsoleIOTests_test_partial_reads in test_winconsoleio.o
      _WindowsConsoleIOTests_test_partial_surrogate_reads in test_winconsoleio.o
      _WindowsConsoleIOTests_test_ctrl_z in test_winconsoleio.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 14.98s
