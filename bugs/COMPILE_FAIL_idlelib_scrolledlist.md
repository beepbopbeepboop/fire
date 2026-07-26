# COMPILE_FAIL: Lib/idlelib/scrolledlist.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:40:11: warning: unused variable '_tag' [-Wunused-variable]
   40 |         self.frame.destroy()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:45:11: warning: unused variable '_tag' [-Wunused-variable]
   45 |         self.listbox.insert("end", self.default)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
   50 |             self.empty = 0
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:65:11: warning: unused variable '_tag' [-Wunused-variable]
   65 |         self.select(index)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:74:13: warning: unused variable '_tag' [-Wunused-variable]
   74 |         menu = self.menu
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py: In function 'ScrolledList___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:36:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   36 |         # Mark as empty
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:34:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   34 |         listbox.bind("<Key-Up>", self.up_event)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:35:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   35 |         listbox.bind("<Key-Down>", self.down_event)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:24:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   24 |         vbar["command"] = listbox.yview
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:24:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   24 |         vbar["command"] = listbox.yview
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:274:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:272:7: warning: variable '_t90' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:271:11: warning: variable '_t89' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:270:7: warning: variable '_t88' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:269:11: warning: variable '_t87' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:268:10: warning: variable '_t86' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:267:11: warning: variable '_t85' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:266:10: warning: variable '_t84' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:265:11: warning: variable '_t83' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:264:11: warning: variable '_t82' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:263:7: warning: variable '_t81' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:262:11: warning: variable '_t80' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/scrolledlist.py:261:10: warning: variable '_t79' set but not used [-Wunused-but-set-variable]
... (465 more lines)
```

Exit code: 1
Elapsed: 10.63s
