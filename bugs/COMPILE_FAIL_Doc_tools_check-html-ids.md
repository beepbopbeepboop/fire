# COMPILE_FAIL: Doc/tools/check-html-ids.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/check-html-ids.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_IDGatherer_feed", referenced from:
      _get_ids_from_file_0c85c9 in check-html-ids.o
      _get_ids_from_file_0c85c9 in check-html-ids.o
  "_super", referenced from:
      _IDGatherer___init__ in check-html-ids.o
      _get_ids_from_file_0c85c9 in check-html-ids.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.57s
