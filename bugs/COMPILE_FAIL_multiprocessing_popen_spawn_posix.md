# COMPILE_FAIL: Lib/multiprocessing/popen_spawn_posix.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/popen_spawn_posix.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_set_spawning_popen", referenced from:
      _Popen__launch in popen_spawn_posix.o
      _Popen__launch in popen_spawn_posix.o
  "_super", referenced from:
      _Popen___init__ in popen_spawn_posix.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 11.27s
