# COMPILE_FAIL: Doc/tools/extensions/pydoc_topics.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/pydoc_topics.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_status_iterator", referenced from:
      _PydocTopicsBuilder_write_documents in pydoc_topics.o
  "_super", referenced from:
      _PydocTopicsBuilder_init in pydoc_topics.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.32s
