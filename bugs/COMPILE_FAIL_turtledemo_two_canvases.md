# COMPILE_FAIL: Lib/turtledemo/two_canvases.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:15:11: warning: unused variable '_tag' [-Wunused-variable]
   15 |     cv1.pack()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:20:11: warning: unused variable '_tag' [-Wunused-variable]
   20 |     s2 = TurtleScreen(cv2)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:25:11: warning: unused variable '_tag' [-Wunused-variable]
   25 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:40:11: warning: unused variable '_tag' [-Wunused-variable]
   40 |         for t in p, q:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:49:13: warning: unused variable '_tag' [-Wunused-variable]
   49 |     return "EVENTLOOP"
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:233:11: warning: variable '_t116' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:232:11: warning: variable '_t115' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:230:11: warning: variable '_t113' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:228:9: warning: variable '_t111' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:225:11: warning: variable '_t108' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:212:9: warning: variable '_t95' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:209:11: warning: variable '_t92' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:208:11: warning: variable '_t91' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:192:11: warning: variable '_t76' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:182:9: warning: variable '_t66' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:177:9: warning: variable '_t61' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:174:11: warning: variable '_t58' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:171:11: warning: variable '_t55' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:159:11: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:158:11: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:156:11: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:151:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:148:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:147:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:145:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:140:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:133:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:132:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:128:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:127:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:123:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:121:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/two_canvases.py:117:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
... (43 more lines)
```

Exit code: 1
Elapsed: 14.64s
