# COMPILE_FAIL: Tools/c-analyzer/distutils/unixccompiler.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/unixccompiler.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_gen_preprocess_options", referenced from:
      _UnixCCompiler_preprocess in unixccompiler.o
  "_newer", referenced from:
      _UnixCCompiler_preprocess in unixccompiler.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.84s
