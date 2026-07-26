# COMPILE_FAIL: Lib/email/utils.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/utils.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:71:11: warning: unused variable '_tag' [-Wunused-variable]
   71 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:76:11: warning: unused variable '_tag' [-Wunused-variable]
   76 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:81:11: warning: unused variable '_tag' [-Wunused-variable]
   81 |     realname in case realname is not ASCII safe.  Can be an instance of str or
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:96:11: warning: unused variable '_tag' [-Wunused-variable]
   96 |             encoded_name = charset.header_encode(name)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:105:13: warning: unused variable '_tag' [-Wunused-variable]
  105 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py: In function '_has_surrogates_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:61:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   61 |     # Turn any escaped bytes into unicode 'unknown' char.  If the escaped
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:324:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  324 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:320:10: warning: unused variable '_t7' [-Wunused-variable]
  320 |     if tz is None:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:314:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  314 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py: In function '_sanitize_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:78:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   78 |     returned unmodified.
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:77:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   77 |     If the first element of pair is false, then the second element is
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:76:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   76 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:75:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   75 |     for an RFC 2822 From, To or Cc header.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/utils.py:72:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   72 | def formataddr(pair, charset='utf-8'):
      |          ^~~
... (272 more lines)
```

Exit code: 1
Elapsed: 9.48s
