# COMPILE_FAIL: Lib/idlelib/tooltip.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:70:11: warning: unused variable '_tag' [-Wunused-variable]
   70 |     def hidetip(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:75:11: warning: unused variable '_tag' [-Wunused-variable]
   75 |         if tw:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:80:11: warning: unused variable '_tag' [-Wunused-variable]
   80 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:95:11: warning: unused variable '_tag' [-Wunused-variable]
   95 |         super().__init__(anchor_widget)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:104:13: warning: unused variable '_tag' [-Wunused-variable]
  104 |         try:
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py: In function 'TooltipBase___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:233:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:231:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:230:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:229:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py: In function 'TooltipBase___del__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:28:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   28 |         if self.tipwindow:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:26:7: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   26 |     def showtip(self):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py: In function 'TooltipBase_showtip':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:42:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   42 |         self.position_window()
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:51:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   51 |         root_y = self.anchor_widget.winfo_rooty() + y
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:45:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   45 |         self.tipwindow.lift()  # work around bug in Tk 8.5.18+ (issue #24570)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:41:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   41 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:41:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   41 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/tooltip.py:32:1: warning: label 'bb_4' defined but not used [-Wunused-label]
... (1641 more lines)
```

Exit code: 1
Elapsed: 10.37s
