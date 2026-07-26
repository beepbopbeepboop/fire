# COMPILE_FAIL: Tools/c-analyzer/c_parser/parser/_compound_decl_body.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_compound_decl_body.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_log_match", referenced from:
      __parse_struct_next_7a6366 in _compound_decl_body.o
      __parse_struct_next_7a6366 in _compound_decl_body.o
  "_set_capture_groups", referenced from:
      __toplevel in _compound_decl_body.o
      __toplevel in _compound_decl_body.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 15.57s
