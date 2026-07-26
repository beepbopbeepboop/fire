# COMPILE_FAIL: CC ERROR: invalid type argument of unary 'X' (have 'X' {aka 'X'})

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:77:11: warning: unused variable '_tag' [-Wunused-variable]
   77 | TOP_CLASSES = {
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:82:11: warning: unused variable '_tag' [-Wunused-variable]
   82 |     SubTuple: ([1, 2, 3],),
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:87:11: warning: unused variable '_tag' [-Wunused-variable]
   87 | ]
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:102:11: warning: unused variable '_tag' [-Wunused-variable]
  102 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:111:13: warning: unused variable '_tag' [-Wunused-variable]
  111 |         self.value = value
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py: In function 'SpamOkay_okay':
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:189:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:187:9: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py: In function 'SpamFull_staticmeth':
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:28:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   28 |     c: object
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:26:9: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   26 |     a: object
      |         ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py: In function 'SpamFull_classmeth':
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:39:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   39 |         return super().__new__(cls)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:37:9: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   37 | 
      |         ^  
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py: In function 'SpamFull___new__':
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:45:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   45 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:43:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   43 |         self.b = b
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:42:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   42 |         self.a = a
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:41:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   41 |     def __init__(self, a, b, c):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py: In function 'SpamFull___init__':
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:48:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   48 |     # ...
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/_crossinterp_definitions.py:46:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]

```

## Affected files

- `Lib/test/_crossinterp_definitions.py`
