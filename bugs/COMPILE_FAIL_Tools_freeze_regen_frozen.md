# COMPILE_FAIL: Tools/freeze/regen_frozen.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/freeze/regen_frozen.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_compile", referenced from:
      _get_module_code_584a43 in regen_frozen.o
      __gimple_main in regen_frozen.o
      __toplevel in regen_frozen.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 15.92s
