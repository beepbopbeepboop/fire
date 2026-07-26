# COMPILE_FAIL: Lib/test/test_urllib2net.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py: In function '_alloc_TransientResource':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:155:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  155 |         # cannot be made established, we shouldn't leave an open socket object.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py: In function '_retry_thrice_f545f8':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:32:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   32 |         return _retry_thrice(func, exc, *args, **kwargs)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:377:11: warning: variable 'last_exc' set but not used [-Wunused-but-set-variable]
  377 |     @support.requires_resource('walltime')
      |           ^~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:364:10: warning: unused variable '_t9' [-Wunused-variable]
  364 |             finally:
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py: In function '_alloc__wrap_with_retry_thrice_wrapped_env':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:49:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   49 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py: In function '_wrap_with_retry_thrice_wrapped':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:61:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   61 |                 if getattr(value, attr) != attr_value:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:59:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   59 |                 if not hasattr(value, attr):
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:58:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   58 |             for attr, attr_value in self.attrs.items():
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:57:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   57 |         if type_ is not None and issubclass(self.exc, type_):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py: In function 'TransientResource___init__':
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:44:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   44 |     is in effect that matches the specified exception and attributes."""
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:42:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   42 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:41:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   41 | class TransientResource(object):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:40:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   40 | 
      |              ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:39:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   39 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_urllib2net.py:38:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   38 |                                               urllib.error.URLError)
... (2450 more lines)
```

Exit code: 1
Elapsed: 13.90s
