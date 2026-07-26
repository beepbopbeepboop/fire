# COMPILE_FAIL: Lib/idlelib/idle_test/test_warning.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_warning.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_RunWarnTest_assertEqual", referenced from:
      _RunWarnTest_test_run_show in test_warning.o
  "_RunWarnTest_assertIs", referenced from:
      _RunWarnTest_test_showwarnings in test_warning.o
      _RunWarnTest_test_showwarnings in test_warning.o
      _RunWarnTest_test_showwarnings in test_warning.o
  "_ShellWarnTest_assertEqual", referenced from:
      _ShellWarnTest_test_idle_formatter in test_warning.o
      _ShellWarnTest_test_shell_show in test_warning.o
  "_ShellWarnTest_assertIs", referenced from:
      _ShellWarnTest_test_showwarnings in test_warning.o
      _ShellWarnTest_test_showwarnings in test_warning.o
      _ShellWarnTest_test_showwarnings in test_warning.o
  "_captured_stderr", referenced from:
      _RunWarnTest_test_run_show in test_warning.o
      _ShellWarnTest_test_shell_show in test_warning.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 12.81s
