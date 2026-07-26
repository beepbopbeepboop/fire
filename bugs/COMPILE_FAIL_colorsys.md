# COMPILE_FAIL: Lib/colorsys.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/colorsys.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:29:11: warning: unused variable '_tag' [-Wunused-variable]
   29 | ONE_THIRD = 1.0/3.0
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:34:11: warning: unused variable '_tag' [-Wunused-variable]
   34 | # Y: perceived grey level (0.0 == black, 1.0 == white)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:39:11: warning: unused variable '_tag' [-Wunused-variable]
   39 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:63:13: warning: unused variable '_tag' [-Wunused-variable]
   63 |     if g > 1.0:
      |             ^~~ 
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function 'rgb_to_hls_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:96:15: error: invalid operands to binary % (have 'double' and 'double')
   96 |     h = (h/6.0) % 1.0
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_v_37269f':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:110:13: error: invalid operands to binary % (have 'double' and 'double')
  110 |     hue = hue % 1.0
      |             ^
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function 'rgb_to_hsv_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:142:15: error: invalid operands to binary % (have 'double' and 'double')
  142 |     h = (h/6.0) % 1.0
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function 'hsv_to_rgb_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:148:3: error: cannot convert to a pointer type
  148 |     i = int(h*6.0) # XXX assume int() truncates!
      |   ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:173:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function 'hsv_to_rgb_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:169:1: warning: control reaches end of non-void function [-Wreturn-type]
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:50:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
   50 | 
      |             ^                   
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:81:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
   81 |     if minc == maxc:
      |               ^~~~~~         
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:52:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
   52 |     g = y - 0.27478764629897834*i - 0.6356910791873801*q
... (33 more lines)
```

Exit code: 1
Elapsed: 9.38s
