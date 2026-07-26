# COMPILE_FAIL: Lib/idlelib/zoomheight.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:43:11: warning: unused variable '_tag' [-Wunused-variable]
   43 |         try:
      |           ^~  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:48:11: warning: unused variable '_tag' [-Wunused-variable]
   48 |         if height != maxheight:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:53:11: warning: unused variable '_tag' [-Wunused-variable]
   53 |             # Restore the window's height.
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:68:11: warning: unused variable '_tag' [-Wunused-variable]
   68 |             # Get window geometry info for maximized windows.
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:77:13: warning: unused variable '_tag' [-Wunused-variable]
   77 |             top.update()
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function 'ZoomHeight___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:166:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:164:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:163:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:162:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:161:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:160:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:159:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function 'ZoomHeight_zoom_height_event':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:41:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   41 |             return None
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:38:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   38 |         if top.wm_state() != 'normal':
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:36:10: warning: variable 'menu_status' set but not used [-Wunused-but-set-variable]
   36 |         width, height, x, y = get_window_geometry(top)
      |          ^~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:30:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   30 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function 'ZoomHeight_zoom_height':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:61:1: warning: label 'bb_12' defined but not used [-Wunused-label]
   61 |         top = self.top
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:54:1: warning: label 'bb_13' defined but not used [-Wunused-label]
   54 |             #
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:55:1: warning: label 'bb_11' defined but not used [-Wunused-label]
... (228 more lines)
```

Exit code: 1
Elapsed: 10.10s
