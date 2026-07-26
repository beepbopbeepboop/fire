# COMPILE_FAIL: CC ERROR: expected 'X', 'X' or 'X' before 'X'

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:214:63: error: expected ';', ',' or ')' before 'default'
  214 |        (?:\s+|[-\/])
      |                                                               ^      
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py: In function '_alloc_Cookie':
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:251:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  251 |     08-Feb-94 14:15:29 GMT              -- rfc850 format (no weekday)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py: In function '_alloc_DefaultCookiePolicy':
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:265:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  265 |         mon = MONTHS_LOWER.index(g[1].lower()) + 1
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:720:4: error: 'cookie__dispatch_t' has no member named 'get_nonstandard_attr'; did you mean 'set_nonstandard_attr'?
  720 |         #a = h[:i]  # this line is only here to show what a is
      |    ^    ~~~~~~~~~~~~~~~
      |    set_nonstandard_attr
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:720:68: error: expected ';', ',' or ')' before 'default'
  720 |         #a = h[:i]  # this line is only here to show what a is
      |                                                                    ^      
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:720:77: error: expected '}' before 'Cookie_get_nonstandard_attr'
  720 |         #a = h[:i]  # this line is only here to show what a is
      |                                                                             ^                          
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:717:52: note: to match this '{'
  717 |     """
      |                                                    ^
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py: In function '_debug':
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:1043:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
 1043 |                 undotted_domain = domain[1:]
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:1038:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
 1038 |                        "travel", "eu") and len(tld) == 2:
      |           ^  
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
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:110:15: error: invalid operands to binary % (have 'char *' and 'MojoList *')
  110 |     return "%04d-%02d-%02d %02d:%02d:%02dZ" % (
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/http/cookiejar.py:109:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  109 |         dt = datetime.datetime.fromtimestamp(
```

## Affected files

- `Lib/http/cookiejar.py`
