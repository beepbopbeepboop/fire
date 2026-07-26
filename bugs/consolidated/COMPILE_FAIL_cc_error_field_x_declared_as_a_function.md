# COMPILE_FAIL: CC ERROR: field 'X' declared as a function

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
In file included from encoder.ci:7:
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:37:11: error: field '__builtin_huge_valf' declared as a function
   37 | def py_encode_basestring(s):
      |           ^~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:51:4: error: expected '=' before '(' token
   51 | 
      |    ^       
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:52:3: error: expected '}' before '.' token
   52 |     """
      |   ^
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:46:37: note: to match this '{'
   46 | encode_basestring = (c_encode_basestring or py_encode_basestring)
      |                                     ^
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:113:11: warning: unused variable '_tag' [-Wunused-variable]
  113 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:118:11: warning: unused variable '_tag' [-Wunused-variable]
  118 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:123:11: warning: unused variable '_tag' [-Wunused-variable]
  123 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:138:11: warning: unused variable '_tag' [-Wunused-variable]
  138 |         If specified, separators should be an (item_separator,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:147:13: warning: unused variable '_tag' [-Wunused-variable]
  147 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function 'py_encode_basestring_replace':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:297:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  297 |             separator = _item_separator
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:295:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  295 |         else:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:294:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  294 |             buf += newline_indent
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:293:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  293 |             separator = _item_separator + newline_indent
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:292:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  292 |             newline_indent = '\n' + _indent * _current_indent_level
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:291:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  291 |             _current_indent_level += 1
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:290:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  290 |         if _indent is not None:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:289:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  289 |         buf = '['
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:288:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  288 |             markers[markerid] = lst
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function 'py_encode_basestring_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:50:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   50 |   
```

## Affected files

- `Lib/json/encoder.py`
