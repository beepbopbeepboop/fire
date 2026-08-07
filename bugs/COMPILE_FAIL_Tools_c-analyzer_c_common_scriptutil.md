# COMPILE_FAIL: Tools/c-analyzer/c_common/scriptutil.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/scriptutil.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current failure is an honest up-front refusal, not a GCC error:

```
Error building: cannot compile module: function(s) _iter_filenames
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, nor an event
loop / suspend-resume codegen for async functions, yet, so these cannot
be represented as compiled C without emitting silently wrong or broken
code; falling back to interpreting this module from source instead
```

Generator codegen refusal, part of the separate, already-tracked
compiled-generator/async-codegen project (tasks #95-135) — not
investigated further here per that project's scope.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py: In function 'configure_logger_7a6366':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:86:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:85:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:83:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:82:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:78:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:72:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:63:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   63 |         print(*args, **kwargs)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:62:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   62 |             return
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py: In function '_alloc_hide_emit_errors_restore_env':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:44:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   44 |     Rather than printing a message describing the error, we show nothing.
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py: In function 'hide_emit_errors_restore':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:58:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   58 |         self.verbosity = verbosity
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:56:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   56 | class Printer:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:55:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   55 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:54:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   54 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:53:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   53 |     return restore
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:52:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   52 |         logging.raiseExceptions = orig
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py: In function 'hide_emit_errors':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:57:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   57 |     def __init__(self, verbosity=VERBOSITY):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py: In function 'logging_Printer___init__':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:60:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   60 |     def info(self, *args, **kwargs):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:58:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   58 |         self.verbosity = verbosity
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py: In function 'logging_Printer_info':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/logging.py:65:1: warning: label 'bb_4' defined but not used [-Wunused-label]
... (1070 more lines)
```

Exit code: 1
Elapsed: 14.62s
