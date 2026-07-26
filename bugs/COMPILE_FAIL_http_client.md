# COMPILE_FAIL: Lib/http/client.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/http/client.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/http/client.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:272:11: warning: unused variable '_tag' [-Wunused-variable]
  272 |         # self.fp is buffered or not.  So, no self.fp.read() by
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/client.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:277:11: warning: unused variable '_tag' [-Wunused-variable]
  277 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/http/client.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:282:11: warning: unused variable '_tag' [-Wunused-variable]
  282 |         # clients.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/client.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:297:11: warning: unused variable '_tag' [-Wunused-variable]
  297 |         line = str(self.fp.readline(_MAXLINE + 1), "iso-8859-1")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/client.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:306:13: warning: unused variable '_tag' [-Wunused-variable]
  306 |                                      " response")
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/http/client.py: In function '_encode_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:622:10: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  622 |                 chunk_left = self._get_chunk_left()
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:613:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  613 |         except IncompleteRead as exc:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:612:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  612 |             return b''.join(value)
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:608:10: warning: unused variable '_t7' [-Wunused-variable]
  608 |                 value.append(self._safe_read(chunk_left))
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:602:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  602 |             while (chunk_left := self._get_chunk_left()) is not None:
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/http/client.py: In function '_strip_ipv6_iface_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:184:11: warning: format '%ld' expects argument of type 'long int', but argument 2 has type 'int64_t' {aka 'long long int'} [-Wformat=]
  184 |         assert enc_name.startswith(b'['), enc_name
      |           ^~~~~~~  ~~~~~~~~
      |                    |
      |                    int64_t {aka long long int}
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:219:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  219 |     """Reads potential header lines into a list from a file pointer.
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:213:11: warning: variable '_' set but not used [-Wunused-but-set-variable]
  213 |                 hit = 0
      |           ^
/Users/mrs/net/Python-3.14.6/Lib/http/client.py:210:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
... (7145 more lines)
```

Exit code: 1
Elapsed: 10.00s
