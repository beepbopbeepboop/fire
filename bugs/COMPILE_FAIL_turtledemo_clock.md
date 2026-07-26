# COMPILE_FAIL: Lib/turtledemo/clock.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:111:11: warning: unused variable '_tag' [-Wunused-variable]
  111 |         second_hand.setheading(6*sekunde)  # or here
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:116:11: warning: unused variable '_tag' [-Wunused-variable]
  116 |         tracer(True)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:121:11: warning: unused variable '_tag' [-Wunused-variable]
  121 | def main():
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:136:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:145:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py: In function 'display_date_time':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:59:8: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
   59 |     writer.write(wochentag(now), align="center", font=dtfont)
      |        ^
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:88:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
   88 |     writer.bk(85)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:86:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
   86 |     writer.ht()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:83:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
   83 |         hand.speed(0)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:81:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
   81 |         hand.resizemode("user")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:76:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   76 |     minute_hand.color("blue1", "red1")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:74:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   74 |     minute_hand = Turtle()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:66:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   66 |     mode("logo")
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py: In function 'setup':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:161:11: warning: variable '_t90' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:160:11: warning: variable '_t89' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:158:11: warning: variable '_t87' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:156:11: warning: variable '_t85' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:150:11: warning: variable '_t80' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:149:11: warning: variable '_t79' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/clock.py:147:11: warning: variable '_t77' set but not used [-Wunused-but-set-variable]
... (102 more lines)
```

Exit code: 1
Elapsed: 23.88s
