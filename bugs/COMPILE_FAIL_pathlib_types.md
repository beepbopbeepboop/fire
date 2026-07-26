# COMPILE_FAIL: Lib/pathlib/types.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/pathlib/types.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "__PathGlobber", referenced from:
      __JoinablePath_full_match in types.o
      __ReadablePath_full_match in types.o
      __ReadablePath_glob in types.o
      __WritablePath_full_match in types.o
  "_copyfileobj", referenced from:
      __WritablePath__copy_from in types.o
      __WritablePath__copy_from in types.o
  "_ensure_different_files", referenced from:
      __WritablePath__copy_from in types.o
      __WritablePath__copy_from in types.o
  "_ensure_distinct_paths", referenced from:
      __ReadablePath_copy in types.o
  "_magic_open", referenced from:
      __ReadablePath_read_bytes in types.o
      __ReadablePath_read_text in types.o
      __WritablePath_write_bytes in types.o
      __WritablePath_write_text in types.o
      __WritablePath_write_text in types.o
      __WritablePath__copy_from in types.o
      __WritablePath__copy_from in types.o
      __WritablePath__copy_from in types.o
      __WritablePath__copy_from in types.o
      ...
  "_memoryview", referenced from:
      __WritablePath_write_bytes in types.o
  "_text_encoding", referenced from:
      __ReadablePath_read_text in types.o
      __WritablePath_write_text in types.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 11.54s
