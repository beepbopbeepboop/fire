# COMPILE_FAIL: Tools/build/verify_ensurepip_wheels.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/verify_ensurepip_wheels.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_urlopen", referenced from:
      _verify_wheel_584a43 in verify_ensurepip_wheels.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 15.14s
