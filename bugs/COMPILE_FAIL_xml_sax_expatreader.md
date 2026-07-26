# COMPILE_FAIL: Lib/xml/sax/expatreader.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py: In function '_alloc_ExpatLocator':
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:74:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   74 |         if parser is None:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py: In function '_alloc_ExpatParser':
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:88:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   88 |         self._namespaces = namespaceHandling
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py: In function '_alloc__ClosedParser':
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:102:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  102 |         try:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py: In function 'ExpatLocator___init__':
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:436:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  436 |     def skipped_entity_handler(self, name, is_pe):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:434:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  434 |         return 1
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:433:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  433 |         del self._entity_stack[-1]
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py: In function 'ExpatLocator_getColumnNumber':
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:60:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   60 |     def getLineNumber(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:64:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   64 |         return parser._parser.ErrorLineNumber
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:73:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   73 |         parser = self._ref
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:71:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   71 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:70:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   70 |         return parser._source.getPublicId()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:69:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   69 |             return None
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:68:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   68 |         if parser is None:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:67:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   67 |         parser = self._ref
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/expatreader.py:66:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   66 |     def getPublicId(self):
... (3135 more lines)
```

Exit code: 1
Elapsed: 13.08s
