# COMPILE_FAIL: Lib/turtledemo/penrose.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:123:11: warning: unused variable '_tag' [-Wunused-variable]
  123 |     tracer(1)
      |           ^~~ 
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:128:11: warning: unused variable '_tag' [-Wunused-variable]
  128 |     pu()
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:133:11: warning: unused variable '_tag' [-Wunused-variable]
  133 |     global tiledict
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:148:11: warning: unused variable '_tag' [-Wunused-variable]
  148 |         a = clock()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:157:13: warning: unused variable '_tag' [-Wunused-variable]
  157 |     mode("logo")
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py: In function 'inflatekite_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:56:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   56 |     rt(144)
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:52:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   52 |     fl = f * l
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py: In function 'inflatedart_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:78:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   78 |     rt(180)
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:74:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   74 |     fl = f * l
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py: In function 'draw_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:103:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  103 | def sun(l, n):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py: In function 'test_737363':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:143:1: warning: label 'bb_13' defined but not used [-Wunused-label]
  143 |     print("%d kites and %d darts = %d pieces." % (nk, nd, nk+nd))
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:142:1: warning: label 'bb_7' defined but not used [-Wunused-label]
  142 |     nd = len([x for x in tiledict if not tiledict[x]])
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py: In function 'demo_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/penrose.py:148:9: error: implicit declaration of function 'clock' [-Wimplicit-function-declaration]
  148 |         a = clock()
      |         ^~~~~
... (61 more lines)
```

Exit code: 1
Elapsed: 16.72s
