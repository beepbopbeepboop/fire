# COMPILE_FAIL: Lib/xml/etree/ElementInclude.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:45:11: warning: unused variable '_tag' [-Wunused-variable]
   45 | # See https://www.python.org/psf/license for licensing details.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
   50 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:55:11: warning: unused variable '_tag' [-Wunused-variable]
   55 | XINCLUDE = "{http://www.w3.org/2001/XInclude}"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:70:11: warning: unused variable '_tag' [-Wunused-variable]
   70 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:79:13: warning: unused variable '_tag' [-Wunused-variable]
   79 | # @param parse Parse mode.  Either "xml" or "text".
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py: In function 'default_loader_89c6a7':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:171:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  171 |                     node.tail = (node.tail or "") + text
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py: In function '_include_bb5aa0':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:173:7: error: 'MojoList' has no member named 'text'
  173 |                     elem.text = (elem.text or "") + text
      |       ^ 
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:285:11: warning: variable '_t146' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:283:11: warning: variable '_t144' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:195:7: warning: variable '_t57' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:194:13: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:179:7: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
  179 |                 )
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:162:10: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
  162 |                 text = loader(href, parse, e.get("encoding"))
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:80:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
   80 | # @param encoding Optional text encoding (UTF-8 by default for "text").
      |             ^~~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:97:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
   97 | 
      |               ^              
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:68:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
   68 |     pass
      |               ^                  
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementInclude.py:59:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
... (25 more lines)
```

Exit code: 1
Elapsed: 14.34s
