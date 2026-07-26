# COMPILE_FAIL: Tools/c-analyzer/distutils/ccompiler.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/ccompiler.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "___import__", referenced from:
      _new_compiler_737363 in ccompiler.o
  "_split_quoted", referenced from:
      _CCompiler___init__ in ccompiler.o
      _CCompiler_set_executables in ccompiler.o
      _CCompiler_set_executable in ccompiler.o
  "_vars", referenced from:
      _new_compiler_737363 in ccompiler.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 15.94s
