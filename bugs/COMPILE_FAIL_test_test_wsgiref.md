# COMPILE_FAIL: Lib/test/test_wsgiref.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py: In function '_alloc_ErrorHandler':
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:288:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  288 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py: In function '_alloc_TestHandler':
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:302:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  302 |         util.setup_testing_defaults(env)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py: In function 'MockServer___init__':
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:806:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  806 |             h.run(hello_app)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:804:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  804 |         msg = "should not do partial writes"
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:803:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  803 |         h = SimpleHandler(BytesIO(), PartialWriter(), sys.stderr, environ)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:802:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  802 |         environ = {"SERVER_PROTOCOL": "HTTP/1.0"}
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:801:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  801 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:800:16: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  800 |                 pass
      |                ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:799:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  799 |             def flush(self):
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:798:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  798 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py: In function 'MockServer_server_bind':
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:49:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   49 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:47:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   47 |         pass
      |           ^~  
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:46:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   46 |     def finish(self):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:45:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   45 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_wsgiref.py:44:11: warning: variable 'port' set but not used [-Wunused-but-set-variable]
   44 |         self.rfile, self.wfile = self.connection
      |           ^~~~
... (6667 more lines)
```

Exit code: 1
Elapsed: 13.21s
