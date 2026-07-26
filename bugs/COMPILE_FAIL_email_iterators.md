# COMPILE_FAIL: Lib/email/iterators.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:25:11: warning: unused variable '_tag' [-Wunused-variable]
   25 |     yield self
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:30:11: warning: unused variable '_tag' [-Wunused-variable]
   30 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:35:11: warning: unused variable '_tag' [-Wunused-variable]
   35 |     Optional decode (default False) is passed through to .get_payload().
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
   50 |     for subpart in msg.walk():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:59:13: warning: unused variable '_tag' [-Wunused-variable]
   59 |         fp = sys.stdout
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function 'walk_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:149:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:143:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:142:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function 'body_line_iterator_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:40:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   40 |             yield from StringIO(payload)
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:38:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   38 |         payload = subpart.get_payload(decode=decode)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function 'typed_subpart_iterator_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:47:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   47 |     "text".  Optional 'subtype' is the MIME subtype to match against; if
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:45:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   45 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_structure_7a6366':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:63:15: error: invalid operands to binary % (have 'char *' and 'int64_t' {aka 'long long int'})
   63 |         print(' [%s]' % msg.get_default_type(), file=fp)
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:89:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:58:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   58 |     if fp is None:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py:78:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/iterators.py: At top level:
... (36 more lines)
```

Exit code: 1
Elapsed: 10.51s
