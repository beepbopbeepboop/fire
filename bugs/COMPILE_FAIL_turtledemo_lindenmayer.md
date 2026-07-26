# COMPILE_FAIL: Lib/turtledemo/lindenmayer.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:79:11: warning: unused variable '_tag' [-Wunused-variable]
   79 |     ################################
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:84:11: warning: unused variable '_tag' [-Wunused-variable]
   84 |         color("red")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:89:11: warning: unused variable '_tag' [-Wunused-variable]
   89 |         color("black")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:104:11: warning: unused variable '_tag' [-Wunused-variable]
  104 |     speed(0)
      |           ^~  
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:113:13: warning: unused variable '_tag' [-Wunused-variable]
  113 | if __name__=='__main__':
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py: In function 'main_r':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:43:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   43 |                 pass
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py: In function 'main_l':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:59:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   59 |         forward(7.5)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py: In function 'main_f':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:62:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   62 |     snake_replacementRules = {"b": "b+f+b--f--b+f+b"}
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py: In function 'main_A':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:66:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   66 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:64:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   64 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py: In function 'main_B':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:96:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   96 |         color("green")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:94:10: warning: variable 'l' set but not used [-Wunused-but-set-variable]
   94 | 
      |          ^
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/lindenmayer.py:93:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   93 |         forward(l)
      |          ^~~
... (75 more lines)
```

Exit code: 1
Elapsed: 23.36s
