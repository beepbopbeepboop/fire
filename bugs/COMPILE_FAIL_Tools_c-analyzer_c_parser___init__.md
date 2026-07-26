# COMPILE_FAIL: Tools/c-analyzer/c_parser/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "__get_preprocessor", referenced from:
      _parse_file_7a6366 in __init__.o
      _parse_files_7a6366 in __init__.o
  "__match_glob", referenced from:
      __resolve_max_size_1ce6ce in __init__.o
  "__parse", referenced from:
      __parse_file_7a6366 in __init__.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.03s
