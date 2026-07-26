# COMPILE_FAIL: CC ERROR: 'X' redeclared as different kind of symbol

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:65:11: warning: unused variable '_tag' [-Wunused-variable]
   65 |     def _(self): pass
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:70:11: warning: unused variable '_tag' [-Wunused-variable]
   70 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:75:11: warning: unused variable '_tag' [-Wunused-variable]
   75 |     def __(self): pass
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:90:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:99:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:155:6: error: '__a' redeclared as different kind of symbol
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:41:3: note: previous declaration of '__a' with type '__a'
   41 |     def _(self): pass
      |   ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:156:6: error: '___' redeclared as different kind of symbol
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:36:3: note: previous declaration of '___' with type '___'
   36 | 
      |   ^  
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:159:13: error: expected declaration specifiers or '...' before '___'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:160:13: error: expected declaration specifiers or '...' before '___'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:163:13: error: expected declaration specifiers or '...' before '___'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:164:13: error: expected declaration specifiers or '...' before '___'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:165:14: error: expected declaration specifiers or '...' before '___'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:166:14: error: expected declaration specifiers or '...' before '___'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:167:13: error: expected declaration specifiers or '...' before '___'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:168:13: error: expected declaration specifiers or '...' before '___'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:169:14: error: expected declaration specifiers or '...' before '___'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:170:14: error: expected declaration specifiers or '...' before '___'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:171:15: error: expected declaration specifiers or '...' before '___'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:172:15: error: expected declaration specifiers or '...' before '___'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:179:13: error: expected declaration specifiers or '...' before '__a'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:180:13: error: expected declaration specifiers or '...' before '__a'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:181:14: error: expected declaration specifiers or '...' before '__a'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:182:14: error: expected declaration specifiers or '...' before '__a'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:183:15: error: expected declaration specifiers or '...' before '__a'
/Users/mrs/net/Python-3.14.6/Lib/test/pyclbr_input.py:184:15: err
```

## Affected files

- `Lib/test/pyclbr_input.py`
