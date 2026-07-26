# COMPILE_FAIL: Lib/turtledemo/forest.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:31:11: warning: unused variable '_tag' [-Wunused-variable]
   31 |         lst = []
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:36:11: warning: unused variable '_tag' [-Wunused-variable]
   36 |                         180 - 11 * level + symRandom(15),
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 |             for angle, sizefactor in branchlist:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
   56 |     t.left(90)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:65:13: warning: unused variable '_tag' [-Wunused-variable]
   65 |     return t
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py: In function 'randomfd_7a6366':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:37:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   37 |                         0 )
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:36:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   36 |                         180 - 11 * level + symRandom(15),
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:28:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   28 |     # benutzt Liste von turtles und Liste von Zweiglisten,
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:27:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   27 | def tree(tlist, size, level, widthfactor, branchlists, angledist=10, sizedist=5):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py: In function 'tree_545dc0':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:97:7: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
   97 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:83:11: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
   83 |     tracer(75,0)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:82:11: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
   82 |     p.ht()
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:80:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
   80 | def main():
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/forest.py:79:11: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
   79 | # Hier 3 Baumgeneratoren:
      |           ^~~~
... (133 more lines)
```

Exit code: 1
Elapsed: 24.22s
