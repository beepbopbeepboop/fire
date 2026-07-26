# COMPILE_FAIL: Lib/xml/dom/xmlbuilder.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py: In function '_alloc_DOMBuilder':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:118:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  118 |         ("create_entity_ref_nodes", 0): [
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py: In function '_alloc_DOMEntityResolver':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:132:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  132 |             ("cdata_sections", 0)],
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py: In function '_alloc_DOMInputSource':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:146:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  146 |             ("validate_if_schema", 0),
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py: In function '_alloc_Options':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:160:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  160 |     }
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py: In function 'DOMBuilder___init__':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:444:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:442:13: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:441:13: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py: In function 'DOMBuilder__get_entityResolver':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:65:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   65 |     def _get_errorHandler(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:63:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   63 |         self.entityResolver = entityResolver
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py: In function 'DOMBuilder__set_entityResolver':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:68:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   68 |         self.errorHandler = errorHandler
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:66:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   66 |         return self.errorHandler
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py: In function 'DOMBuilder__get_errorHandler':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:70:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   70 |     def _get_filter(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:68:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   68 |         self.errorHandler = errorHandler
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py: In function 'DOMBuilder__set_errorHandler':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:73:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   73 |         self.filter = filter
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py:71:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   71 |         return self.filter
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/xmlbuilder.py: In function 'DOMBuilder__get_filter':
... (1488 more lines)
```

Exit code: 1
Elapsed: 14.32s
