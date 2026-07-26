# COMPILE_FAIL: Lib/html/parser.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/html/parser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:114:11: warning: unused variable '_tag' [-Wunused-variable]
  114 |         p.feed(data)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:119:11: warning: unused variable '_tag' [-Wunused-variable]
  119 |     self.handle_startendtag(); end tags by self.handle_endtag().  The
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:124:11: warning: unused variable '_tag' [-Wunused-variable]
  124 |     corresponding Unicode character (and self.handle_data() is no
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:139:11: warning: unused variable '_tag' [-Wunused-variable]
  139 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:148:13: warning: unused variable '_tag' [-Wunused-variable]
  148 |         self.convert_charrefs = convert_charrefs
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py: In function '_replace_attr_charref_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:315:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  315 |                     break
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:314:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  314 |                     # incomplete
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:309:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  309 |                 if match:
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:302:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  302 |                     self.handle_charref(name)
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:298:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  298 |             elif startswith("&#", i):
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py: In function '_unescape_attrvalue_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:110:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  110 |     """Find tags and other markup and call handler functions.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py: In function 'HTMLParser___init__':
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:118:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  118 |     Start tags are handled by calling self.handle_starttag() or
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:116:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  116 |         p.close()
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/html/parser.py:115:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  115 |         ...
... (3691 more lines)
```

Exit code: 1
Elapsed: 10.03s
