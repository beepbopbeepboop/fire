# COMPILE_FAIL: Lib/test/test_zoneinfo/_support.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_zoneinfo/_support.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_import_fresh_module", referenced from:
      _get_modules in _support.o
  "_object", referenced from:
      _set_zoneinfo_module_0c85c9 in _support.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 15.56s
