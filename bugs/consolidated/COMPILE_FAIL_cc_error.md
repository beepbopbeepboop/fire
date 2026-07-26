# COMPILE_FAIL: CC ERROR: 

**7 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:37:11: warning: unused variable '_tag' [-Wunused-variable]
   37 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:42:11: warning: unused variable '_tag' [-Wunused-variable]
   42 |     KEY_LEFT = Ctrl-B, KEY_RIGHT = Ctrl-F, KEY_UP = Ctrl-P,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:47:11: warning: unused variable '_tag' [-Wunused-variable]
   47 |         self.insert_mode = insert_mode
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:62:11: warning: unused variable '_tag' [-Wunused-variable]
   62 |         last = self.maxx
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:71:13: warning: unused variable '_tag' [-Wunused-variable]
   71 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py: In function 'rectangle_737363':
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:247:11: warning: variable '_t75' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:245:11: warning: variable '_t73' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:242:11: warning: variable '_t70' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:240:11: warning: variable '_t68' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:238:11: warning: variable '_t66' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:235:11: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:233:11: warning: variable '_t61' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:231:11: warning: variable '_t59' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:228:11: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:226:11: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:224:11: warning: variable '_t52' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:221:11: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:219:11: warning: variable '_t47' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:218:11: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:214:11: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:211:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:208:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:207:11: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/textpad.py:203:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
  203 |         return Textbox(win).edit()
      |           ^~~~
/Users/mrs/net/Python-3.14.
```

## Affected files

- `Lib/curses/textpad.py`
- `Lib/test/libregrtest/logger.py`
- `Lib/test/test_asyncio/test_sock_lowlevel.py`
- `Lib/test/test_dbm_sqlite3.py`
- `Lib/test/test_hashlib.py`
- `Lib/test/test_remote_pdb.py`
- `Lib/unittest/result.py`
