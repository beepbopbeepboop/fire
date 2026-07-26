# COMPILE_FAIL: Lib/ctypes/_endian.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/ctypes/_endian.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_issubclass", referenced from:
      __other_endian_0c85c9 in _endian.o
  "_super", referenced from:
      __swapped_meta___setattr__ in _endian.o
      __swapped_meta___setattr__ in _endian.o
      __swapped_struct_meta___setattr__ in _endian.o
      __swapped_struct_meta___setattr__ in _endian.o
      __swapped_union_meta___setattr__ in _endian.o
      __swapped_union_meta___setattr__ in _endian.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.96s
