# COMPILE_FAIL: Tools/msi/csv_to_wxs.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/msi/csv_to_wxs.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_defaultdict", referenced from:
      __gimple_main in csv_to_wxs.o
      __gimple_main in csv_to_wxs.o
      __gimple_main in csv_to_wxs.o
  "_uuid1", referenced from:
      __gimple_main in csv_to_wxs.o
      __gimple_main in csv_to_wxs.o
  "_zip_longest", referenced from:
      __gimple_main in csv_to_wxs.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.19s
