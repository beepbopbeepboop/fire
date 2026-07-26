# COMPILE_FAIL: Lib/test/test_urllib.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:344:11: warning: unused variable '_tag' [-Wunused-variable]
  344 |                 # test suite.  They use different url opening codepaths.  Plain
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:349:11: warning: unused variable '_tag' [-Wunused-variable]
  349 |                 InvalidURL = http.client.InvalidURL
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:354:11: warning: unused variable '_tag' [-Wunused-variable]
  354 |                     InvalidURL, f"contain control.*{escaped_char_repr}"):
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:369:11: warning: unused variable '_tag' [-Wunused-variable]
  369 |             # calls urllib.parse.quote() on the URL which makes all of the
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:378:13: warning: unused variable '_tag' [-Wunused-variable]
  378 |             self.unfakehttp()
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:699:271: warning: hex escape sequence out of range
  699 |     def test_reporthook_0_bytes(self):
      |                                                                                                                                                                                                                                                                               ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:699:271: warning: hex escape sequence out of range
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:733:37: warning: hex escape sequence out of range
  733 |             os_helper.TESTFN, hooktester)
      |                                     ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:745:45: warning: hex escape sequence out of range
  745 |         self.addCleanup(urllib.request.urlcleanup)
      |                                             ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:773:67: warning: hex escape sequence out of range
  773 | Connection: close
      |                                                                   ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:776:43: warning: hex escape sequence out of range
  776 | 
      |                                           ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:784:66: warning: hex escape sequence out of range
  784 | 
      |                                                                  ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py: In function 'hexescape_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:1016:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
 1016 |                          "using unquote(): not all characters escaped: "
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py: In function 'FakeHTTPMixin_fakehttp':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:105:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  105 |         self.text = bytes("test_urllib: %s\n" % self.__class__.__name__,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib.py:103:10: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
... (17040 more lines)
```

Exit code: 1
Elapsed: 14.33s
