# COMPILE_FAIL: Lib/xml/dom/expatbuilder.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py: In function '_alloc_ElementInfo':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:210:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  210 |             pass
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py: In function '_alloc_ExpatBuilder':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:224:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  224 |         doc = self.document
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py: In function '_alloc_ExpatBuilderNS':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:238:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  238 |                                    has_internal_subset):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py: In function '_alloc_FilterVisibilityController':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:252:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  252 |                 doctype.entities._seq = []
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py: In function '_alloc_FragmentBuilder':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:266:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  266 |         node = self.document.createProcessingInstruction(target, data)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py: In function '_alloc_FragmentBuilderNS':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:280:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  280 |         elif childNodes and childNodes[-1].nodeType == TEXT_NODE:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py: In function '_alloc_InternalSubsetExtractor':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:294:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  294 |             node = childNodes[-1]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py: In function 'ElementInfo___init__':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:1114:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:1112:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:1111:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:1110:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:1109:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py: In function 'ElementInfo___getstate__':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:78:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   78 |                 if t[0] == "(":
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py: In function 'ElementInfo___setstate__':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:84:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   84 |     def getAttributeTypeNS(self, namespaceURI, localName):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:82:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   82 |         return minidom._no_type
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:81:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   81 |                     return _typeinfo_map[info[-2]]
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/expatbuilder.py:80:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
... (20402 more lines)
```

Exit code: 1
Elapsed: 14.55s
