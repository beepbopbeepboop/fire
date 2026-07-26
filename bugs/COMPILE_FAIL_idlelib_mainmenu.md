# COMPILE_FAIL: Lib/idlelib/mainmenu.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:29:11: warning: unused variable '_tag' [-Wunused-variable]
   29 |    ('_Path Browser', '<<open-path-browser>>'),
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:34:11: warning: unused variable '_tag' [-Wunused-variable]
   34 |    None,
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:39:11: warning: unused variable '_tag' [-Wunused-variable]
   39 |    ]),
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 |    ('R_eplace...', '<<replace>>'),
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:63:13: warning: unused variable '_tag' [-Wunused-variable]
   63 |  ('format', [
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:126:3: error: implicit declaration of function '_gimple_main' [-Wimplicit-function-declaration]
  126 |     main('idlelib.idle_test.test_mainmenu', verbosity=2)
      |   ^ ~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:632:7: warning: variable '_t384' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:249:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:137:5: error: conflicting types for 'main'; have 'int(int,  const char **)'
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:104:16: note: previous declaration of 'main' with type 'int64_t()' {aka 'long long int()'}
  104 |    ('Show _Line Numbers', '<<toggle-line-numbers>>'),
      |                ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:148:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:81:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
   81 |    ]),
      |               ^              
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:52:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
   52 |    ('Find _Selection', '<<find-selection>>'),
      |               ^~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:43:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
   43 |    ('_Redo', '<<redo>>'),
      |            ^~~~~~~~~~~~~~             
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:38:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
   38 |    ('E_xit IDLE', '<<close-all-windows>>'),
      |                   ^~~~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:33:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
   33 |    ('Save Cop_y As...', '<<save-copy-of-window-as-file>>'),
      |             ^~~~~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/mainmenu.py:28:16: warning: '_mojo_dispatch_getattr' defined but not used [-Wunused-function]
   28 |    ('Module _Browser', '<<open-class-browser>>'),
... (21 more lines)
```

Exit code: 1
Elapsed: 10.88s
