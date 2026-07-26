# COMPILE_FAIL: Lib/encodings/_win_cp_codecs.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/encodings/_win_cp_codecs.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_code_page_decode", referenced from:
      _create_win32_code_page_codec_decode in _win_cp_codecs.o
  "_code_page_encode", referenced from:
      _create_win32_code_page_codec_encode in _win_cp_codecs.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 11.06s
