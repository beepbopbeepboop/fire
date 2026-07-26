# COMPILE_FAIL: Lib/tomllib/_re.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:49:11: warning: unused variable '_tag' [-Wunused-variable]
   49 | )?
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:59:11: warning: unused variable '_tag' [-Wunused-variable]
   59 |     or datetime.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:74:11: warning: unused variable '_tag' [-Wunused-variable]
   74 |     year, month, day = int(year_str), int(month_str), int(day_str)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:83:13: warning: unused variable '_tag' [-Wunused-variable]
   83 |     elif zulu_time:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py: In function 'match_to_datetime_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:260:11: warning: variable 'tz' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:245:10: warning: variable '_t64' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:244:11: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:208:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:204:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:200:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:196:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:192:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:188:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:184:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:180:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:176:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:172:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:168:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:165:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py: In function 'cached_tz_854698':
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:103:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  103 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:101:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  101 |     )
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py: In function 'match_to_localtime_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:107:10: error: implicit declaration of function 'time' [-Wimplicit-function-declaration]
  107 |     return time(int(hour_str), int(minute_str), int(sec_str), micros)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/tomllib/_re.py:1:1: note: 'time' is defined in header '<time.h>'; this is probably fixable by adding '#include <time.h>'
  +++ |+#include <time.h>
... (58 more lines)
```

Exit code: 1
Elapsed: 19.28s
