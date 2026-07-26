# COMPILE_FAIL: Lib/idlelib/idle_test/test_filelist.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_filelist.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_FileListTest_assertEqual", referenced from:
      _FileListTest_test_new_empty in test_filelist.o
      _FileListTest_test_new_empty in test_filelist.o
  "_requires", referenced from:
      _FileListTest_setUpClass in test_filelist.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.37s
