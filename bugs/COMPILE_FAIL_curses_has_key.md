# COMPILE_FAIL: Lib/curses/has_key.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:27:11: warning: unused variable '_tag' [-Wunused-variable]
   27 |     _curses.KEY_DC: 'kdch1',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:32:11: warning: unused variable '_tag' [-Wunused-variable]
   32 |     _curses.KEY_ENTER: 'kent',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:37:11: warning: unused variable '_tag' [-Wunused-variable]
   37 |     _curses.KEY_F1: 'kf1',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 |     _curses.KEY_F23: 'kf23',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:61:13: warning: unused variable '_tag' [-Wunused-variable]
   61 |     _curses.KEY_F31: 'kf31',
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py: In function 'has_key_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:439:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:188:19: error: invalid operands to binary % (have 'char *' and 'MojoList *')
  188 |                 L.append( 'Mismatch for key %s, system=%i, Python=%i'
      |                   ^
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:202:1: warning: label 'bb_8' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:1287:11: warning: variable '_t1100' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:1283:7: warning: variable '_t1096' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:1274:11: warning: variable '_t1087' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:1257:11: warning: variable '_t1072' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:1245:11: warning: variable '_t1061' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:1241:10: warning: unused variable '_t1058' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:233:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:79:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
   79 |     _curses.KEY_F48: 'kf48',
      |               ^~~~~~~~~~~~~~ 
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:50:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
   50 |     _curses.KEY_F21: 'kf21',
      |               ^~~~~~~~~~~~~~     
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:41:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
   41 |     _curses.KEY_F13: 'kf13',
      |            ^~~~~~~~~~~~~~~~~          
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:36:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
   36 |     _curses.KEY_F0: 'kf0',
      |                   ^~~~~~~~             
/Users/mrs/net/Python-3.14.6/Lib/curses/has_key.py:31:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
   31 |     _curses.KEY_END: 'kend',
... (21 more lines)
```

Exit code: 1
Elapsed: 9.35s
