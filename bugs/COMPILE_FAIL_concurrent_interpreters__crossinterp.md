# COMPILE_FAIL: Lib/concurrent/interpreters/_crossinterp.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:64:11: warning: unused variable '_tag' [-Wunused-variable]
   64 |     def __new__(cls):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:69:11: warning: unused variable '_tag' [-Wunused-variable]
   69 | #        return f'interpreters._queues.UNBOUND'
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:74:11: warning: unused variable '_tag' [-Wunused-variable]
   74 | UNBOUND_REMOVE = object()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:89:11: warning: unused variable '_tag' [-Wunused-variable]
   89 |     except KeyError:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:98:13: warning: unused variable '_tag' [-Wunused-variable]
   98 |         raise NotImplementedError(f'unsupported unbound replacement op {flag!r}')
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function 'classonly___init__':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:186:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:184:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:183:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:182:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:181:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:180:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:179:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:178:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py: In function 'classonly___set_name__':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:45:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   45 |             doc = doc.replace(
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:37:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   37 |     """
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:30:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   30 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:28:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   28 |         # called on the class
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:27:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   27 |             raise AttributeError(self.name)
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:26:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   26 |         if obj is not None:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_crossinterp.py:25:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
... (281 more lines)
```

Exit code: 1
Elapsed: 9.54s
