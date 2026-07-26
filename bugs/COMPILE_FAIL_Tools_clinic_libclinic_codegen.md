# COMPILE_FAIL: Tools/clinic/libclinic/codegen.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/codegen.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_fail", referenced from:
      _Destination___post_init__ in codegen.o
      _Destination___post_init__ in codegen.o
      _Destination___post_init__ in codegen.o
      _Destination_clear in codegen.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.58s
