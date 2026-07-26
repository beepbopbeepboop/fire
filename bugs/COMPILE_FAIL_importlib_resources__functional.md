# COMPILE_FAIL: Lib/importlib/resources/_functional.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/_functional.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_as_file", referenced from:
      _path in _functional.o
      _path in _functional.o
  "_files", referenced from:
      _open_binary in _functional.o
      _open_binary in _functional.o
      _open_text in _functional.o
      _open_text in _functional.o
      _read_binary in _functional.o
      _read_binary in _functional.o
      _read_text in _functional.o
      _read_text in _functional.o
      ...
  "_object", referenced from:
      __toplevel in _functional.o
      _main in _functional.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 11.96s
