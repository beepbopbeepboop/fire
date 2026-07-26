# COMPILE_FAIL: Doc/tools/extensions/changes.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/changes.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_sphinx_gettext", referenced from:
      _expand_version_arg_abb124 in changes.o
      _PyVersionChange_run in changes.o
      _DeprecatedRemoved_run in changes.o
      _SoftDeprecated_run in changes.o
  "_super", referenced from:
      _PyVersionChange_run in changes.o
      _DeprecatedRemoved_run in changes.o
      _SoftDeprecated_run in changes.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.52s
