# COMPILE_FAIL: Lib/idlelib/statusbar.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py: In function '_alloc_MultiStatusBar':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:30:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   30 |     frame = Frame(top)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py: In function 'MultiStatusBar___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:211:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:209:14: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:208:14: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:207:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:206:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:205:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:204:20: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:203:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:202:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py: In function 'MultiStatusBar_set_label':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:21:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   21 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:24:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   24 |     from tkinter.ttk import Frame, Button
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:19:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   19 |         label.config(text=text)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:17:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   17 |         if width != 0:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:46:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   46 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:37:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   37 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:35:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   35 |     msb.set_label("two", "world")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:34:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   34 |     msb.set_label("one", "hello")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:33:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
   33 |     msb = MultiStatusBar(frame)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:32:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
   32 |     text.pack()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:31:9: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
   31 |     text = Text(frame, height=5, width=40)
      |         ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/statusbar.py:30:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
... (176 more lines)
```

Exit code: 1
Elapsed: 10.51s
