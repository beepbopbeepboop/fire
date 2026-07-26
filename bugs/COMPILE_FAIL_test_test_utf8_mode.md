# COMPILE_FAIL: Lib/test/test_utf8_mode.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:85:11: warning: unused variable '_tag' [-Wunused-variable]
   85 |                                   PYTHONLEGACYWINDOWSFSENCODING='1')
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:90:11: warning: unused variable '_tag' [-Wunused-variable]
   90 |         if not self.posix_locale():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:95:11: warning: unused variable '_tag' [-Wunused-variable]
   95 |         # invalid mode
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:110:11: warning: unused variable '_tag' [-Wunused-variable]
  110 |             expected = 'utf-8/surrogateescape'
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:119:13: warning: unused variable '_tag' [-Wunused-variable]
  119 |                                   PYTHONUTF8='strict',
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py: In function 'UTF8ModeTests_posix_locale':
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:272:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  272 |         proc = subprocess.run(cmd, text=True)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:270:9: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  270 |         cmd = [sys.executable, '-X', 'utf8', '-c', code]
      |         ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:269:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  269 |                 f'out.close()')
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:268:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  268 |                 f'print(os.isatty(fd), os.device_encoding(fd), file=out); '
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:267:14: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  267 |                 f'out = open({filename!r}, "w", encoding="utf-8"); '
      |              ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:266:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  266 |         code = (f'import os, sys; fd = sys.stdout.fileno(); '
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:265:11: warning: variable 'loc' set but not used [-Wunused-but-set-variable]
  265 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:264:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  264 |         self.addCleanup(os_helper.unlink, filename)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:263:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  263 |         filename = 'out.txt'
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_utf8_mode.py:262:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
... (2134 more lines)
```

Exit code: 1
Elapsed: 13.61s
