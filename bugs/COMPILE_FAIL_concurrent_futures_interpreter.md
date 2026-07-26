# COMPILE_FAIL: Lib/concurrent/futures/interpreter.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/concurrent/futures/interpreter.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_InterpreterPoolExecutor__counter", referenced from:
      _InterpreterPoolExecutor___init__ in interpreter.o
  "_super", referenced from:
      _InterpreterPoolExecutor___init__ in interpreter.o
      _InterpreterPoolExecutor___init__ in interpreter.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 11.01s
