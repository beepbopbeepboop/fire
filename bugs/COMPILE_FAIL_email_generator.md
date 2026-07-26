# COMPILE_FAIL: Lib/email/generator.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/generator.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:167:11: warning: unused variable '_tag' [-Wunused-variable]
  167 |     def _write(self, msg):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:172:11: warning: unused variable '_tag' [-Wunused-variable]
  172 |         # parameter.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:177:11: warning: unused variable '_tag' [-Wunused-variable]
  177 |         # Do The Right Thing, and can still modify the Content-Type: header if
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:192:11: warning: unused variable '_tag' [-Wunused-variable]
  192 |             if msg.get('content-transfer-encoding') is None:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:201:13: warning: unused variable '_tag' [-Wunused-variable]
  201 |             self._write_headers(msg)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py: In function 'Generator___init__':
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:65:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   65 |         self._fp = outfp
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:65:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   65 |         self._fp = outfp
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:65:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   65 |         self._fp = outfp
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:67:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   67 |         self.maxheaderlen = maxheaderlen
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:46:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   46 |         is not set), escapes From_ lines in the body of the message by putting
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:385:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  385 |     def _make_boundary(cls, text=None):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:383:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  383 |     # at the end of the module.  It *is* internal, so we could drop that...
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:382:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  382 |     #   _make_boundary = Generator._make_boundary
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:381:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  381 |     # for backward compatibility by doing
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/generator.py:380:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
... (6764 more lines)
```

Exit code: 1
Elapsed: 12.64s
