# COMPILE_FAIL: Tools/c-analyzer/c_parser/parser/_func_body.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_func_body.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_log_match", referenced from:
      _parse_function_statics_132aaf in _func_body.o
      __parse_next_local_static_737363 in _func_body.o
      __parse_next_local_static_737363 in _func_body.o
  "_set_capture_groups", referenced from:
      __toplevel in _func_body.o
      __toplevel in _func_body.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.27s
