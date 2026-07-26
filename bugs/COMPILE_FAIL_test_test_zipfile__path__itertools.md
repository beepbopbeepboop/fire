# COMPILE_FAIL: Lib/test/test_zipfile/_path/_itertools.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/_itertools.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_deque", referenced from:
      _consume_1ce6ce in _itertools.o
  "_islice", referenced from:
      _consume_1ce6ce in _itertools.o
  "_next", referenced from:
      _Counter___next__ in _itertools.o
      _consume_1ce6ce in _itertools.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 17.10s
