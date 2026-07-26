# COMPILE_FAIL: Lib/http/server.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/http/server.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/http/server.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:400:11: warning: unused variable '_tag' [-Wunused-variable]
  400 |         if is_http_0_9:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/server.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:405:11: warning: unused variable '_tag' [-Wunused-variable]
  405 |         try:
      |           ^~  
/Users/mrs/net/Python-3.14.6/Lib/http/server.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:410:11: warning: unused variable '_tag' [-Wunused-variable]
  410 |                 HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE,
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/http/server.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:425:11: warning: unused variable '_tag' [-Wunused-variable]
  425 |         elif (conntype.lower() == 'keep-alive' and
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/server.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:434:13: warning: unused variable '_tag' [-Wunused-variable]
  434 |                 return False
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/http/server.py: In function 'HTTPServer_server_bind':
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:940:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  940 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:938:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
  938 |         -- note however that this the default server uses this
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:937:7: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
  937 |         the block size or perhaps to replace newlines by CRLF
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:936:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
  936 |         The only reason for overriding this would be to change
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:935:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
  935 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:934:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  934 |         anything with a write() method).
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:933:11: warning: variable 'port' set but not used [-Wunused-but-set-variable]
  933 |         argument is a file object open for writing (or
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:932:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  932 |         (or anything with a read() method) and the DESTINATION
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:931:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  931 |         The SOURCE argument is a file object open for reading
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/server.py:930:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
... (15526 more lines)
```

Exit code: 1
Elapsed: 9.84s
