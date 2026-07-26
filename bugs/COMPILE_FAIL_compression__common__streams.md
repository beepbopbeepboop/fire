# COMPILE_FAIL: Lib/compression/_common/_streams.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/compression/_common/_streams.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_BaseStream_readable", referenced from:
      _BaseStream__check_can_read in _streams.o
      _BaseStream__check_can_seek in _streams.o
  "_BaseStream_seekable", referenced from:
      _BaseStream__check_can_seek in _streams.o
      _BaseStream__check_can_seek in _streams.o
  "_BaseStream_writable", referenced from:
      _BaseStream__check_can_write in _streams.o
  "_DecompressReader__decomp_factory", referenced from:
      _DecompressReader___init__ in _streams.o
      _DecompressReader_mojo_read in _streams.o
      _DecompressReader__rewind in _streams.o
      _DecompressReader_seek in _streams.o
  "_memoryview", referenced from:
      _DecompressReader_readinto in _streams.o
  "_super", referenced from:
      _DecompressReader_mojo_close in _streams.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 11.05s
