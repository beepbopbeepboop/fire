# COMPILE_FAIL: Lib/idlelib/calltip.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py: In function '___main___toplevel':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:29:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:24:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:17:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:22:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:27:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:42:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:51:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip.py: In function 'Calltip___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip.py:30:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   30 |         self._calltip_window = None
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip.py:25:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   25 |             self.text = editwin.text
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:180:1: warning: label 'bb_3' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:174:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:172:7: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:171:7: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:170:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:169:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:168:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:167:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:166:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:165:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:164:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:163:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:162:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:161:9: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip.py: In function 'Calltip_mojo_close':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip.py:37:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   37 |         if self.active_calltip:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip.py:35:7: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   35 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip.py: In function 'Calltip__make_tk_calltip_window':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip.py:40:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   40 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip.py:38:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   38 |             self.active_calltip.hidetip()
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip.py:37:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
... (622 more lines)
```

Exit code: 1
Elapsed: 10.43s
