# COMPILE_FAIL: Tools/scripts/divmod_threshold.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/scripts/divmod_threshold.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_divmod", referenced from:
      _probe_den_0c85c9 in divmod_threshold.o
  "_divmod_fast", referenced from:
      _probe_den_0c85c9 in divmod_threshold.o
  "_now", referenced from:
      _probe_den_0c85c9 in divmod_threshold.o
      _probe_den_0c85c9 in divmod_threshold.o
      _probe_den_0c85c9 in divmod_threshold.o
  "_randrange", referenced from:
      _rand_digits_0c85c9 in divmod_threshold.o
      _probe_den_0c85c9 in divmod_threshold.o
      _probe_den_0c85c9 in divmod_threshold.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.06s
