# COMPILE_FAIL: Lib/test/test_webbrowser.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py: In function '_alloc_MockPopenPipe':
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:360:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  360 |         url = "https://python.org"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py: In function '_alloc_PopenMock':
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:374:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  374 |     def test_default_browser_lookup(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py: In function 'PopenMock_poll':
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:669:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:667:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py: In function 'PopenMock_wait':
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:35:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   35 | class CommandTestMixin:
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:33:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   33 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py: In function 'CommandTestMixin__test':
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:80:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   80 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:78:11: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
   78 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:77:10: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
   77 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:76:7: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
   76 |                    arguments=[URL])
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:75:10: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
   75 |                    options=[],
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:74:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
   74 |         self._test('open',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:73:11: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
   73 |     def test_open(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:72:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
   72 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:71:10: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
   71 |     browser_class = webbrowser.GenericBrowser
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_webbrowser.py:70:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
   70 | 
      |           ^   
... (5183 more lines)
```

Exit code: 1
Elapsed: 12.90s
