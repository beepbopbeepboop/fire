# COMPILE_FAIL: Lib/turtledemo/round_dance.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:95:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:100:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:105:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:120:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:129:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py: In function 'stop':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:198:9: warning: variable 'running' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:27:8: error: conflicting types for '_gimple_main'; have 'char *(void)'
   27 |     global running
      |        ^~~~~~~~~~~ 
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:83:9: note: previous declaration of '_gimple_main' with type 'int64_t()' {aka 'long long int()'}
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:95:11: warning: variable '_t55' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:94:11: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:92:9: warning: variable '_t52' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:89:11: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:88:11: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:74:7: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
   74 |             shapesize(cs)
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:58:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
   58 |             dancers.append(clone())
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:57:10: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   57 |         if i % 12 == 0:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:52:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
   52 |     for i in range(180):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py: In function 'main':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:90:10: error: returning 'char *' from a function with return type 'int' makes integer from pointer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:80:7: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
   80 |     print(main())
      |       ^
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:95:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:147:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:118:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:109:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:104:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:99:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/round_dance.py:94:16: warning: '_mojo_dispatch_getattr' defined but not used [-Wunused-function]
... (20 more lines)
```

Exit code: 1
Elapsed: 16.09s
