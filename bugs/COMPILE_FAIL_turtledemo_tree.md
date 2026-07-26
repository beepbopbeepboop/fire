# COMPILE_FAIL: Lib/turtledemo/tree.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:31:11: warning: unused variable '_tag' [-Wunused-variable]
   31 |             lst.append(p)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:36:11: warning: unused variable '_tag' [-Wunused-variable]
   36 | def maketree():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 |     p.getscreen().tracer(30,0)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
   56 | if __name__ == "__main__":
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:65:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py: In function 'tree_4b6796':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:149:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:136:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py: In function 'maketree':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:83:8: error: variable or field 't' declared void
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:46:5: error: invalid use of void expression
   46 |     t = tree([p], 200, 65, 0.6375)
      |     ^
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:83:8: warning: variable 't' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:75:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:73:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:72:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:69:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:67:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:66:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:64:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:63:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:60:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:59:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   59 |     mainloop()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:57:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   57 |     msg = main()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:55:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   55 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py:54:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   54 |     return "done: %.2f sec." % (b-a)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/tree.py: At top level:
... (57 more lines)
```

Exit code: 1
Elapsed: 14.76s
