# COMPILE_FAIL: Lib/wsgiref/handlers.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:285:11: warning: unused variable '_tag' [-Wunused-variable]
  285 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:290:11: warning: unused variable '_tag' [-Wunused-variable]
  290 |             raise AssertionError("write() before start_response()")
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:295:11: warning: unused variable '_tag' [-Wunused-variable]
  295 |             self.send_headers()
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:310:11: warning: unused variable '_tag' [-Wunused-variable]
  310 |         'self.wsgi_file_wrapper'.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:319:13: warning: unused variable '_tag' [-Wunused-variable]
  319 |         'self.headers_sent' is false and it is going to attempt direct
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py: In function 'format_date_time_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:679:11: warning: variable 'z' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:676:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:675:11: warning: variable 'y' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:672:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:668:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:664:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:660:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:656:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:652:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:648:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:644:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:642:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py: In function '_needs_transcode_584a43':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:42:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
   42 |     environ = {}
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:36:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   36 |     enc = sys.getfilesystemencoding()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:30:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   30 | def _needs_transcode(k):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py: In function 'read_environ':
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:166:10: warning: variable '_t125' set but not used [-Wunused-but-set-variable]
  166 |         if self.wsgi_file_wrapper is not None:
      |          ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/wsgiref/handlers.py:165:10: warning: variable '_t124' set but not used [-Wunused-but-set-variable]
  165 | 
... (10272 more lines)
```

Exit code: 1
Elapsed: 14.41s
