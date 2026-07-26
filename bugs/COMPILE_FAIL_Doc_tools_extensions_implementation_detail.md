# COMPILE_FAIL: Doc/tools/extensions/implementation_detail.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/implementation_detail.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_ImplementationDetail_assert_has_content", referenced from:
      _ImplementationDetail_run in implementation_detail.o
  "_ImplementationDetail_parse_content_to_nodes", referenced from:
      _ImplementationDetail_run in implementation_detail.o
  "_ImplementationDetail_set_source_info", referenced from:
      _ImplementationDetail_run in implementation_detail.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.42s
