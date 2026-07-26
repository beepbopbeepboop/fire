# COMPILE_FAIL: Tools/unicode/dawg.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/unicode/dawg.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_bytearray", referenced from:
      _Dawg_compute_packed_compute_chunk in dawg.o
      _Dawg_compute_packed in dawg.o
      __inverse_lookup_d4d5c5 in dawg.o
  "_bytes", referenced from:
      _Dawg_compute_packed in dawg.o
      __inverse_lookup_d4d5c5 in dawg.o
  "_defaultdict", referenced from:
      _Dawg__linearize_edges in dawg.o
      _Dawg__topological_order in dawg.o
  "_hash", referenced from:
      _DawgNode___hash__ in dawg.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.28s
