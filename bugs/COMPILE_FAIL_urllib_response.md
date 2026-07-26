# COMPILE_FAIL: Lib/urllib/response.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/urllib/response.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_addinfo_mojo_close", referenced from:
      _addinfo___exit__ in response.o
  "_addinfourl_mojo_close", referenced from:
      _addinfourl___exit__ in response.o
  "_super", referenced from:
      _addbase___init__ in response.o
      _addclosehook___init__ in response.o
      _addclosehook_mojo_close in response.o
      _addinfo___init__ in response.o
      _addinfourl___init__ in response.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.43s
