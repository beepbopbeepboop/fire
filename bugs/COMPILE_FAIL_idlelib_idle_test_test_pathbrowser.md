# COMPILE_FAIL: Lib/idlelib/idle_test/test_pathbrowser.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_pathbrowser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_DirBrowserTreeItemTest_assertEqual", referenced from:
      _DirBrowserTreeItemTest_test_DirBrowserTreeItem in test_pathbrowser.o
      _DirBrowserTreeItemTest_test_DirBrowserTreeItem in test_pathbrowser.o
      _DirBrowserTreeItemTest_test_DirBrowserTreeItem in test_pathbrowser.o
  "_PathBrowserTest_assertEqual", referenced from:
      _PathBrowserTest_test_settitle in test_pathbrowser.o
      _PathBrowserTest_test_settitle in test_pathbrowser.o
  "_PathBrowserTest_assertIsInstance", referenced from:
      _PathBrowserTest_test_init in test_pathbrowser.o
      _PathBrowserTest_test_rootnode in test_pathbrowser.o
  "_PathBrowserTest_assertIsNotNone", referenced from:
      _PathBrowserTest_test_init in test_pathbrowser.o
  "_PathBrowserTest_assertTrue", referenced from:
      _PathBrowserTest_test_close in test_pathbrowser.o
      _PathBrowserTest_test_close in test_pathbrowser.o
  "_PathBrowserTreeItemTest_assertEqual", referenced from:
      _PathBrowserTreeItemTest_test_PathBrowserTreeItem in test_pathbrowser.o
      _PathBrowserTreeItemTest_test_PathBrowserTreeItem in test_pathbrowser.o
      _PathBrowserTreeItemTest_test_PathBrowserTreeItem in test_pathbrowser.o
  "_requires", referenced from:
      _PathBrowserTest_setUpClass in test_pathbrowser.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.46s
