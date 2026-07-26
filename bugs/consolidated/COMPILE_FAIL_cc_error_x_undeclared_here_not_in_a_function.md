# COMPILE_FAIL: CC ERROR: 'X' undeclared here (not in a function)

**2 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:23:11: warning: unused variable '_tag' [-Wunused-variable]
   23 |     win = curses.newwin(nlines, ncols, uly, ulx)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:28:11: warning: unused variable '_tag' [-Wunused-variable]
   28 |     contents = box.edit()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:33:11: warning: unused variable '_tag' [-Wunused-variable]
   33 |     stdscr.getch()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:48:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:57:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:110:39: error: 'main' undeclared here (not in a function)
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py: In function 'test_textpad_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:21:13: error: invalid operands to binary % (have 'char *' and 'char *')
   21 |     stdscr.addstr(uly-3, ulx, "Use Ctrl-G to end editing (%s)." % mode)
      |             ^
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:203:11: warning: variable '_t71' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:201:11: warning: variable '_t69' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:200:11: warning: variable '_t68' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:191:11: warning: variable '_t60' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:189:11: warning: variable '_t58' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:186:11: warning: variable '_t55' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:183:11: warning: variable '_t52' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:180:11: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:177:11: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:174:11: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:171:11: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:170:10: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:169:11: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:160:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:158:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:156:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/curses_tests.py:155:11: warning: variable '_t
```

## Affected files

- `Lib/test/curses_tests.py`
- `Lib/test/test_unittest/testmock/testmock.py`
