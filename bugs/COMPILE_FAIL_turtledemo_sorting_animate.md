# COMPILE_FAIL: Lib/turtledemo/sorting_animate.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py: In function '_alloc_Block':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:104:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  104 |             store_index = store_index + 1
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py: In function '_alloc_Shelf':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:118:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  118 |     target = list(range(10))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py: In function 'Block___init__':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:385:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:383:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:382:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:381:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:380:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:379:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:378:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:377:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:376:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:375:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:374:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:373:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:372:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:371:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:370:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:369:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py: In function 'Block_glow':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:32:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   32 |     def __repr__(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:30:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   30 |         self.fillcolor("black")
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:29:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   29 |     def unglow(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py: In function 'Block_unglow':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:35:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   35 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:33:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   33 |         return "Block size: {0}".format(self.size)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:32:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   32 |     def __repr__(self):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py: In function 'Block___repr__':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/sorting_animate.py:40:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   40 |         self.y = y
      | ^   
... (412 more lines)
```

Exit code: 1
Elapsed: 14.70s
