# COMPILE_FAIL: Lib/tkinter/commondialog.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/tkinter/commondialog.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "__destroy_temp_root", referenced from:
      _Dialog_show in commondialog.o
  "__get_temp_root", referenced from:
      _Dialog_show in commondialog.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.14s
