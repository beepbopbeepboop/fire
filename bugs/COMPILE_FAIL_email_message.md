# COMPILE_FAIL: Lib/email/message.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/message.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/message.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:181:11: warning: unused variable '_tag' [-Wunused-variable]
  181 |         specified the policy associated with the message instance is used.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/message.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:186:11: warning: unused variable '_tag' [-Wunused-variable]
  186 |         """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/message.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:191:11: warning: unused variable '_tag' [-Wunused-variable]
  191 |                       mangle_from_=False,
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/message.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:206:11: warning: unused variable '_tag' [-Wunused-variable]
  206 |         header.  'policy' is passed to the BytesGenerator instance used to
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/message.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:215:13: warning: unused variable '_tag' [-Wunused-variable]
  215 |         return fp.getvalue()
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/message.py: In function '_splitparam_fa7153':
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:619:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  619 |         message/rfc822.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:615:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  615 |         type this will always return a value.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:611:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  611 |         The returned string is coerced to lower case of the form
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:609:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  609 |         """Return the message's content type.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:608:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  608 |     def get_content_type(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:605:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  605 |     # Use these three methods instead of the three above.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/message.py: In function '_formatparam_6b2260':
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:56:15: error: invalid operands to binary % (have 'char *' and 'MojoList *')
   56 |             return '%s=%s' % (param, value)
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:63:15: error: invalid operands to binary % (have 'char *' and 'MojoList *')
   63 |                 return '%s=%s' % (param, value)
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/email/message.py:67:15: error: invalid operands to binary % (have 'char *' and 'MojoList *')
   67 |             return '%s="%s"' % (param, utils.quote(value))
      |               ^
... (8042 more lines)
```

Exit code: 1
Elapsed: 11.31s
