# COMPILE_FAIL: CC ERROR: non-register as LHS of unary operation

**4 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |         elif self.no_tests_run():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:77:11: warning: unused variable '_tag' [-Wunused-variable]
   77 |         if self.worker_bug:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:82:11: warning: unused variable '_tag' [-Wunused-variable]
   82 |         return ', '.join(state)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:97:11: warning: unused variable '_tag' [-Wunused-variable]
   97 |             exitcode = EXITCODE_BAD_TEST
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:106:13: warning: unused variable '_tag' [-Wunused-variable]
  106 |             case State.PASSED:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py: In function 'TestResults___init__':
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:276:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  276 |         stats = self.stats
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:274:13: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
  274 |         red, reset, yellow = ansi.RED, ansi.RESET, ansi.YELLOW
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:273:13: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
  273 |         ansi = get_colors()
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:272:14: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
  272 |         # Total tests
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:271:14: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
  271 |     def display_summary(self, first_runtests: RunTests, filtered: bool) -> None:
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:270:7: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
  270 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:269:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
  269 |             print(f"{yellow}Test suite interrupted by signal SIGINT.{reset}")
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:268:14: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  268 |             print()
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:267:14: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  267 |         if self.interrupted:
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:266:9: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  266 | 
      |         ^   
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:265:9: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  265 |             print(text)
      |         ^   
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/results.py:264:14: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  264 |               
```

## Affected files

- `Lib/test/libregrtest/results.py`
- `Lib/test/mock_socket.py`
- `Lib/test/signalinterproctester.py`
- `Lib/test/test_augassign.py`
