# COMPILE_FAIL: Tools/build/stable_abi.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/stable_abi.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_object", referenced from:
      __toplevel in stable_abi.o
  "_partial", referenced from:
      _gen_python3dll_132aaf in stable_abi.o
      _gen_ctypes_test_ef86f2 in stable_abi.o
      _gen_testcapi_feature_macros_132aaf in stable_abi.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.00s
