# COMPILE_FAIL: Lib/test/test_urllib2_localnet.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py: In function '_alloc_BasicAuthHandler':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:262:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  262 |     def log_message(self, format, *args):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py: In function '_alloc_DigestAuthHandler':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:276:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  276 |                                    "ascii"))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py: In function '_alloc_FakeProxyHandler':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:290:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  290 |         # With Basic Authentication
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py: In function '_alloc_LoopbackHttpServer':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:304:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  304 |         super(BasicAuthTests, self).tearDown()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py: In function '_alloc_LoopbackHttpServerThread':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:318:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  318 |         urllib.request.install_opener(urllib.request.build_opener(ah))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py: In function 'LoopbackHttpServer___init__':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:822:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:820:7: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:819:7: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:818:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:817:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:816:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:815:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:814:24: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:813:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:812:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:811:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:810:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:809:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:808:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:807:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:806:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py: In function 'LoopbackHttpServer_get_request':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:66:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   66 |                                         request_handler)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:61:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   61 |         threading.Thread.__init__(self)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:60:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   60 |     def __init__(self, request_handler):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2_localnet.py:55:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   55 |         return (request, client_address)
... (5190 more lines)
```

Exit code: 1
Elapsed: 14.04s
