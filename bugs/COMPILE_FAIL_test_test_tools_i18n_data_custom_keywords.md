# COMPILE_FAIL: Lib/test/test_tools/i18n_data/custom_keywords.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/i18n_data/custom_keywords.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "__", referenced from:
      __toplevel in custom_keywords.o
  "_bar", referenced from:
      __toplevel in custom_keywords.o
  "_foo", referenced from:
      __toplevel in custom_keywords.o
      __toplevel in custom_keywords.o
  "_nfoo", referenced from:
      __toplevel in custom_keywords.o
      __toplevel in custom_keywords.o
      __toplevel in custom_keywords.o
  "_npfoo", referenced from:
      __toplevel in custom_keywords.o
      __toplevel in custom_keywords.o
      __toplevel in custom_keywords.o
  "_pfoo", referenced from:
      __toplevel in custom_keywords.o
      __toplevel in custom_keywords.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 55.60s
