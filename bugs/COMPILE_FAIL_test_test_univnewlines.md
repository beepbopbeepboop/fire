# COMPILE_FAIL: Lib/test/test_univnewlines.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_univnewlines.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_TestCRLFNewlines_assertEqual", referenced from:
      _TestCRLFNewlines_test_read in test_univnewlines.o
      _TestCRLFNewlines_test_read in test_univnewlines.o
      _TestCRLFNewlines_test_readlines in test_univnewlines.o
      _TestCRLFNewlines_test_readlines in test_univnewlines.o
      _TestCRLFNewlines_test_readline in test_univnewlines.o
      _TestCRLFNewlines_test_readline in test_univnewlines.o
      _TestCRLFNewlines_test_seek in test_univnewlines.o
      _TestCRLFNewlines_test_seek in test_univnewlines.o
      ...
  "_TestCRLFNewlines_mojo_open", referenced from:
      _TestCRLFNewlines_setUp in test_univnewlines.o
      _TestCRLFNewlines_test_read in test_univnewlines.o
      _TestCRLFNewlines_test_readlines in test_univnewlines.o
      _TestCRLFNewlines_test_readline in test_univnewlines.o
      _TestCRLFNewlines_test_seek in test_univnewlines.o
      _TestCRLFNewlines_test_tell in test_univnewlines.o
  "_TestCRNewlines_assertEqual", referenced from:
      _TestCRNewlines_test_read in test_univnewlines.o
      _TestCRNewlines_test_read in test_univnewlines.o
      _TestCRNewlines_test_readlines in test_univnewlines.o
      _TestCRNewlines_test_readlines in test_univnewlines.o
      _TestCRNewlines_test_readline in test_univnewlines.o
      _TestCRNewlines_test_readline in test_univnewlines.o
      _TestCRNewlines_test_seek in test_univnewlines.o
      _TestCRNewlines_test_seek in test_univnewlines.o
      ...
  "_TestCRNewlines_mojo_open", referenced from:
      _TestCRNewlines_setUp in test_univnewlines.o
      _TestCRNewlines_test_read in test_univnewlines.o
      _TestCRNewlines_test_readlines in test_univnewlines.o
      _TestCRNewlines_test_readline in test_univnewlines.o
      _TestCRNewlines_test_seek in test_univnewlines.o
  "_TestGenericUnivNewlines_assertEqual", referenced from:
      _TestGenericUnivNewlines_test_read in test_univnewlines.o
      _TestGenericUnivNewlines_test_read in test_univnewlines.o
      _TestGenericUnivNewlines_test_readlines in test_univnewlines.o
      _TestGenericUnivNewlines_test_readlines in test_univnewlines.o
      _TestGenericUnivNewlines_test_readline in test_univnewlines.o
      _TestGenericUnivNewlines_test_readline in test_univnewlines.o
      _TestGenericUnivNewlines_test_seek in test_univnewlines.o
      _TestGenericUnivNewlines_test_seek in test_univnewlines.o
      ...
  "_TestGenericUnivNewlines_mojo_open", referenced from:
      _TestGenericUnivNewlines_setUp in test_univnewlines.o
      _TestGenericUnivNewlines_test_read in test_univnewlines.o
      _TestGenericUnivNewlines_test_readlines in test_univnewlines.o
      _TestGenericUnivNewlines_test_readline in test_univnewlines.o
      _TestGenericUnivNewlines_test_seek in test_univnewlines.o
... (35 more lines)
```

Exit code: 1
Elapsed: 16.89s
