# COMPILE_FAIL: Lib/json/decoder.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:82:11: warning: unused variable '_tag' [-Wunused-variable]
   82 |     begin = end - 1
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:87:11: warning: unused variable '_tag' [-Wunused-variable]
   87 |         end = chunk.end()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:92:11: warning: unused variable '_tag' [-Wunused-variable]
   92 |         # Terminator is the end of string, a literal control character,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:107:11: warning: unused variable '_tag' [-Wunused-variable]
  107 |             raise JSONDecodeError("Unterminated string starting at",
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:116:13: warning: unused variable '_tag' [-Wunused-variable]
  116 |             end += 1
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py: In function 'JSONDecodeError___init__':
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:278:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  278 |     | number (real) | float             |
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:276:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
  276 |     | number (int)  | int               |
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:275:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
  275 |     +---------------+-------------------+
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:274:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
  274 |     | string        | str               |
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:273:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
  273 |     +---------------+-------------------+
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:272:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
  272 |     | array         | list              |
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:271:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
  271 |     +---------------+-------------------+
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:270:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
  270 |     | object        | dict              |
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:269:10: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
  269 |     +===============+===================+
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/json/decoder.py:268:21: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
... (516 more lines)
```

Exit code: 1
Elapsed: 10.23s
