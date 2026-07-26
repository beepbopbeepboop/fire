# COMPILE_FAIL: CC ERROR: in buildN, at tree.cc:N

**8 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:40:11: warning: unused variable '_tag' [-Wunused-variable]
   40 |             # state, e.g. maximized and full-screen windows.
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:45:11: warning: unused variable '_tag' [-Wunused-variable]
   45 |         except WmInfoGatheringError:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
   50 |             set_window_geometry(top, (width, maxheight, x, maxy))
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:65:11: warning: unused variable '_tag' [-Wunused-variable]
   65 |         if screen_dimensions not in self._max_height_and_y_coords:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:74:13: warning: unused variable '_tag' [-Wunused-variable]
   74 |                 raise WmInfoGatheringError(
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py: In function 'ZoomHeight___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:163:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:161:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:160:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:159:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:158:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:157:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/zoomheight.py:156:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
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
   55 |             # .wm_geometry('')
```

## Affected files

- `Lib/idlelib/zoomheight.py`
- `Lib/test/test_devpoll.py`
- `Lib/test/test_structseq.py`
- `Lib/test/test_userdict.py`
- `Lib/test/test_userstring.py`
- `Lib/test/test_xml_dom_minicompat.py`
- `Tools/c-analyzer/c_parser/datafiles.py`
- `Tools/peg_generator/pegen/grammar_parser.py`
