# COMPILE_FAIL: Tools/tz/zdump.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/tz/zdump.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_array", referenced from:
      _TZInfo_fromfile in zdump.o
      _TZInfo_fromfile in zdump.o
  "_namedtuple", referenced from:
      __toplevel in zdump.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 15.78s
