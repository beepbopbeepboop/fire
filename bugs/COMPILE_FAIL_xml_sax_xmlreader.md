# COMPILE_FAIL: Lib/xml/sax/xmlreader.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:65:11: warning: unused variable '_tag' [-Wunused-variable]
   65 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:70:11: warning: unused variable '_tag' [-Wunused-variable]
   70 |         and warnings; if they cannot support the requested locale,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:75:11: warning: unused variable '_tag' [-Wunused-variable]
   75 |     def getFeature(self, name):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:90:11: warning: unused variable '_tag' [-Wunused-variable]
   90 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:99:13: warning: unused variable '_tag' [-Wunused-variable]
   99 |     finished with a call to close the reset method must be called to
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py: In function 'XMLReader___init__':
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:298:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  298 |             raise KeyError(name)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:296:7: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  296 |     def getNameByQName(self, name):
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:295:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  295 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:294:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  294 |         return self._attrs[name]
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:293:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  293 |     def getValueByQName(self, name):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:292:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  292 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:291:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  291 |         return self._attrs[name]
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:290:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  290 |     def getValue(self, name):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:289:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  289 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/xml/sax/xmlreader.py:288:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
... (1162 more lines)
```

Exit code: 1
Elapsed: 13.18s
