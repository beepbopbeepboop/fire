# COMPILE_FAIL: Lib/test/test_urlparse.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:149:11: warning: unused variable '_tag' [-Wunused-variable]
  149 |         self.assertSequenceEqual(result3, result)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:154:11: warning: unused variable '_tag' [-Wunused-variable]
  154 |         self.assertEqual(result3.fragment, result.fragment)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:159:11: warning: unused variable '_tag' [-Wunused-variable]
  159 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:174:11: warning: unused variable '_tag' [-Wunused-variable]
  174 |         result = urllib.parse.parse_qs(orig, keep_blank_values=False)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:183:13: warning: unused variable '_tag' [-Wunused-variable]
  183 |              ('', '', '/path/to/file', '', '', ''),
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:843:45: warning: hex escape sequence out of range
  843 |         self.assertEqual(p.username, None)
      |                                             ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py: In function 'UrlParseTestCase_checkRoundtrips':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:112:1: warning: label 'bb_4' defined but not used [-Wunused-label]
  112 |         t = (result.scheme, result.netloc, result.path,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:1092:1: warning: label 'bb_3' defined but not used [-Wunused-label]
 1092 |     def test_usingsys(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:1086:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1086 |         self.assertEqual(urllib.parse.urlparse(b"path:80"), (b'path',b'',b'80',b'',b'',b''))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:1084:11: warning: variable '_t233' set but not used [-Wunused-but-set-variable]
 1084 |         self.assertEqual(urllib.parse.urlparse(b"http:80"), (b'http',b'',b'80',b'',b'',b''))
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:1083:10: warning: variable '_t232' set but not used [-Wunused-but-set-variable]
 1083 |         # As usual, need to check bytes input as well
      |          ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:1082:11: warning: variable '_t231' set but not used [-Wunused-but-set-variable]
 1082 |                 ('http','www.python.org:80','','','',''))
      |           ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:1081:10: warning: variable '_t230' set but not used [-Wunused-but-set-variable]
 1081 |         self.assertEqual(urllib.parse.urlparse("http://www.python.org:80"),
      |          ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urlparse.py:1080:10: warning: variable '_t229' set but not used [-Wunused-but-set-variable]
 1080 |         self.assertEqual(urllib.parse.urlparse("https:"),('https','','','','',''))
      |          ^~~~~
... (23573 more lines)
```

Exit code: 1
Elapsed: 14.47s
