# COMPILE_FAIL: Lib/idlelib/calltip_w.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py: In function '_alloc_CalltipWindow':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:66:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   66 |         """
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py: In function 'CalltipWindow___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:326:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:324:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:323:7: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:322:7: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:321:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:320:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:319:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:318:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:317:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:316:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:315:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:314:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:313:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py: In function 'CalltipWindow_get_position':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:42:15: error: invalid operands to binary % (have 'char *' and 'MojoList *')
   42 |         box = self.anchor_widget.bbox("%d.%d" % anchor_index)
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:96:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   96 |         # Hide the call-tip if the insertion cursor moves outside of the
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:69:7: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   69 |         if self.tipwindow or not self.text:
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:47:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   47 |             box[2] = 0
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:41:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   41 |             anchor_index = (curline, 0)
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:38:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   38 |         if curline == self.parenline:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py: In function 'CalltipWindow_position_window':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:57:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   57 |         super().position_window()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:58:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   58 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:83:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   83 |                            background="#ffffd0", foreground="black",
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/calltip_w.py:81:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
   81 |         """Create the call-tip widget."""
... (982 more lines)
```

Exit code: 1
Elapsed: 10.60s
