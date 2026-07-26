# COMPILE_FAIL: Lib/json/encoder.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
In file included from encoder.ci:7:
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:40:11: error: field '__builtin_huge_valf' declared as a function
   40 |     """
      |           ^       
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:54:4: error: expected '=' before '(' token
   54 |         s = match.group(0)
      |    ^    ~~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:55:3: error: expected '}' before '.' token
   55 |         try:
      |   ^
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:49:37: note: to match this '{'
   49 | def py_encode_basestring_ascii(s):
      |                                     ^
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:116:11: warning: unused variable '_tag' [-Wunused-variable]
  116 |         If ensure_ascii is false, the output can contain non-ASCII and
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:121:11: warning: unused variable '_tag' [-Wunused-variable]
  121 |         prevent an infinite recursion (which would cause an RecursionError).
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:126:11: warning: unused variable '_tag' [-Wunused-variable]
  126 |         but is consistent with most JavaScript based encoders and decoders.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:141:11: warning: unused variable '_tag' [-Wunused-variable]
  141 |         representation, you should specify (',', ':') to eliminate
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:150:13: warning: unused variable '_tag' [-Wunused-variable]
  150 |         self.skipkeys = skipkeys
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py: In function 'py_encode_basestring_replace':
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:299:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  299 |             if i:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:297:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  297 |             separator = _item_separator
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:296:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  296 |             newline_indent = None
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:295:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  295 |         else:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/json/encoder.py:294:14: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  294 |             buf += newline_indent
      |              ^~~
... (2140 more lines)
```

Exit code: 1
Elapsed: 10.31s
