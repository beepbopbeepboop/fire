# COMPILE_FAIL: Lib/turtledemo/rosette.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:35:11: warning: unused variable '_tag' [-Wunused-variable]
   35 |     s = Screen()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:40:11: warning: unused variable '_tag' [-Wunused-variable]
   40 |     p.pencolor("red")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:45:11: warning: unused variable '_tag' [-Wunused-variable]
   45 |     at = clock()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:60:11: warning: unused variable '_tag' [-Wunused-variable]
   60 | if __name__ == '__main__':
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:69:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py: In function 'mn_eck_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:187:11: warning: variable '_t47' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:186:11: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:184:11: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:183:11: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:179:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:178:11: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:151:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:150:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:149:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:52:8: error: conflicting types for '_gimple_main'; have 'char *(void)'
   52 |     at = clock()
      |        ^~~~~~~~~   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:15:9: note: previous declaration of '_gimple_main' with type 'int64_t()' {aka 'long long int()'}
   15 | from time import perf_counter as clock, sleep
      |         ^~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:45:10: error: implicit declaration of function 'clock' [-Wimplicit-function-declaration]
   45 |     at = clock()
      |          ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:1:1: note: 'clock' is defined in header '<time.h>'; this is probably fixable by adding '#include <time.h>'
  +++ |+#include <time.h>
    1 | """turtledemo/rosette.py
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:98:11: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:92:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:80:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:79:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:77:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:76:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/rosette.py:74:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
... (54 more lines)
```

Exit code: 1
Elapsed: 16.32s
