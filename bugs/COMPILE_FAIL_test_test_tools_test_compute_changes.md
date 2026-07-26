# COMPILE_FAIL: Lib/test/test_tools/test_compute_changes.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tools/test_compute_changes.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_imports_under_tool", referenced from:
      __toplevel in test_compute_changes.o
  "_process_changed_files", referenced from:
      _TestProcessChangedFiles_test_windows in test_compute_changes.o
      _TestProcessChangedFiles_test_docs in test_compute_changes.o
      _TestProcessChangedFiles_test_macos in test_compute_changes.o
      _TestProcessChangedFiles_test_wasi in test_compute_changes.o
      _TestProcessChangedFiles_test_msi in test_compute_changes.o
      _TestProcessChangedFiles_test_all_run in test_compute_changes.o
      _TestProcessChangedFiles_test_wasi_and_android in test_compute_changes.o
      ...
  "_skip_if_missing", referenced from:
      __toplevel in test_compute_changes.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 18.83s
