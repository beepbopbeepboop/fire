# COMPILE_FAIL: Lib/test/test_xmlrpc.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:535:11: warning: unused variable '_tag' [-Wunused-variable]
  535 |         d = ' 20070908T07:11:13  '
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:540:11: warning: unused variable '_tag' [-Wunused-variable]
  540 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:545:11: warning: unused variable '_tag' [-Wunused-variable]
  545 |         now = datetime.datetime.now()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:560:11: warning: unused variable '_tag' [-Wunused-variable]
  560 |         self.assertTrue(dtime_then >= dstr)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:569:13: warning: unused variable '_tag' [-Wunused-variable]
  569 |         self.assertTrue(dtime != dtuple)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:900:57: warning: hex escape sequence out of range
  900 |             # ignore failures due to non-blocking socket 'unavailable' errors
      |                                                         ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py: In function 'XMLRPCTestCase_test_dump_load':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:1040:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1040 |     request_count = 2
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:1038:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
 1038 | class MultiPathServerTestCase(BaseServerTestCase):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:1037:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
 1037 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:1036:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
 1036 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:1035:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
 1035 |                 self.fail("%s\n%s" % (e, getattr(e, "headers", "")))
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:1034:14: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
 1034 |                 # protocol error; provide additional information in test output
      |              ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:1033:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
 1033 |             if not is_unavailable_exception(e):
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xmlrpc.py:1032:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
 1032 |             # ignore failures due to non-blocking socket unavailable errors.
      |           ^ ~~
... (11085 more lines)
```

Exit code: 1
Elapsed: 13.22s
