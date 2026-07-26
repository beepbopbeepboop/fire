# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/analyze.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/analyze.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_is_funcptr", referenced from:
      _resolve_decl_7a6366 in analyze.o
      __dump_unresolved_132aaf in analyze.o
  "_is_pots", referenced from:
      _resolve_decl_7a6366 in analyze.o
  "_is_system_type", referenced from:
      _resolve_decl_7a6366 in analyze.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.63s
