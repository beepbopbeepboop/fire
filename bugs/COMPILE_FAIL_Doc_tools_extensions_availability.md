# COMPILE_FAIL: Doc/tools/extensions/availability.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/availability.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_Availability_set_source_info", referenced from:
      _Availability_run in availability.o
      _Availability_run in availability.o
  "_sphinx_gettext", referenced from:
      _Availability_run in availability.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.46s
