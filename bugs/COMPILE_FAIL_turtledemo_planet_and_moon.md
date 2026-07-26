# COMPILE_FAIL: Lib/turtledemo/planet_and_moon.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py: In function '_alloc_GravSys':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:99:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   99 |     moon = Star(1, Vec(220,0), Vec(0,295), gs, "planet")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py: In function '_alloc_Star':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:113:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py: In function 'GravSys___init__':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:342:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:340:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:339:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:338:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:337:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py: In function 'GravSys_init':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:31:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   31 |             self.t += self.dt
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:37:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   37 |         Turtle.__init__(self, shape=shape)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:37:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   37 |         Turtle.__init__(self, shape=shape)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:33:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   33 |                 p.step()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:42:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   42 |         gravSys.planets.append(self)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:40:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   40 |         self.setpos(x)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:39:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   39 |         self.m = m
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:38:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   38 |         self.penup()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:37:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   37 |         Turtle.__init__(self, shape=shape)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:36:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   36 |     def __init__(self, m, x, v, gravSys, shape):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:35:9: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   35 | class Star(Turtle):
      |         ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/planet_and_moon.py:34:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   34 | 
      |           ^  
... (479 more lines)
```

Exit code: 1
Elapsed: 16.94s
