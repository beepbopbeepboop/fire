# COMPILE_FAIL: Lib/http/cookiejar.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:289:63: error: expected ';', ',' or ')' before 'default'
  289 |     r"""^
      |                                                               ^      
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py: In function '_alloc_Cookie':
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:326:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  326 |     if m is not None:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py: In function '_alloc_DefaultCookiePolicy':
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:340:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  340 |     """Return unmatched part of re.Match object."""
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:819:4: error: 'cookie__dispatch_t' has no member named 'get_nonstandard_attr'; did you mean 'set_nonstandard_attr'?
  819 |         else: p = ":"+self.port
      |    ^    ~~~~~~~~~~~~~~~
      |    set_nonstandard_attr
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:819:68: error: expected ';', ',' or ')' before 'default'
  819 |         else: p = ":"+self.port
      |                                                                    ^      
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:819:77: error: expected '}' before 'Cookie_get_nonstandard_attr'
  819 |         else: p = ":"+self.port
      |                                                                             ^                          
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:816:52: note: to match this '{'
  816 | 
      |                                                    ^
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py: In function '_debug':
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:1143:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
 1143 |         if cookie.is_expired(self._now):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:1138:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
 1138 |             _debug("   secure cookie with non-secure request")
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py: In function '_warn_unhandled_exception':
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:74:14: error: invalid operands to binary % (have 'char *' and 'int64_t' {aka 'long long int'})
   74 |     warnings.warn("http.cookiejar bug!\n%s" % msg, stacklevel=2)
      |              ^
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:74:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   74 |     warnings.warn("http.cookiejar bug!\n%s" % msg, stacklevel=2)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:71:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   71 |     f = io.StringIO()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:64:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   64 | """
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:63:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   63 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py: In function 'time2isoz_0c85c9':
... (13034 more lines)
```

Exit code: 1
Elapsed: 10.33s
