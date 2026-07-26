# COMPILE_FAIL: Lib/turtledemo/nim.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py: In function '_alloc_Nim':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:128:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  128 |                 self.sticks[(row, col)] = Stick(row, col, game)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py: In function '_alloc_NimController':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:142:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  142 |         self.screen.tracer(True)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py: In function '_alloc_NimModel':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:156:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  156 |         if player == 0:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py: In function '_alloc_NimView':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:170:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  170 |     def notify_over(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py: In function '_alloc_Stick':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:184:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  184 |     def __init__(self, game):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py: In function 'randomrow':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:532:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:531:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py: In function 'randommove_79c856':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:77:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   77 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:73:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
   73 |             self.player = 1
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:61:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   61 |         self.game.view.setup()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py: In function 'NimModel___init__':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:55:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   55 |     def setup(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:53:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   53 |         self.game = game
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py: In function 'NimModel_setup':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:60:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   60 |         self.winner = None
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:107:1: warning: label 'bb_3' defined but not used [-Wunused-label]
  107 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/nim.py:89:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   89 |         turtle.Turtle.__init__(self, visible=False)
... (1643 more lines)
```

Exit code: 1
Elapsed: 22.72s
