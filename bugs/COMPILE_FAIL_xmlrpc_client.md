# COMPILE_FAIL: Lib/xmlrpc/client.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py: In function '_alloc_Binary':
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:275:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  275 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py: In function '_alloc_DateTime':
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:289:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  289 |         elif isinstance(other, str):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py: In function '_alloc_ExpatParser':
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:303:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  303 |             return NotImplemented
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py: In function '_alloc_GzipDecodedResponse':
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:317:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  317 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py: In function '_alloc_Marshaller':
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:331:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  331 |         return time.strptime(self.value, "%Y%m%dT%H:%M:%S")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py: In function '_alloc_MultiCall':
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:345:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  345 |         self.value = str(data).strip()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py: In function '_alloc_MultiCallIterator':
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:359:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  359 |     return datetime.strptime(data, "%Y%m%dT%H:%M:%S")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py: In function '_alloc_ServerProxy':
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:373:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  373 |         else:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py: In function '_alloc_Unmarshaller':
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:387:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  387 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py: In function '_alloc__Method':
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:401:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  401 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py: In function '_alloc__MultiCallMethod':
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:415:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  415 |     def __init__(self, target):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py: In function 'ProtocolError___init__':
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:168:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  168 | APPLICATION_ERROR = -32500
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xmlrpc/client.py:166:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
... (6377 more lines)
```

Exit code: 1
Elapsed: 13.28s
