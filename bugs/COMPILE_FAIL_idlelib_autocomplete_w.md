# COMPILE_FAIL: Lib/idlelib/autocomplete_w.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:85:11: warning: unused variable '_tag' [-Wunused-variable]
   85 |             if self.completions[m] >= s:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:90:11: warning: unused variable '_tag' [-Wunused-variable]
   90 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:95:11: warning: unused variable '_tag' [-Wunused-variable]
   95 |         """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:110:11: warning: unused variable '_tag' [-Wunused-variable]
  110 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:119:13: warning: unused variable '_tag' [-Wunused-variable]
  119 |         while i < min_len and first_comp[i] == last_comp[i]:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py: In function 'AutoCompleteWindow___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:295:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  295 |             # will get KeyError.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:293:9: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  293 |         except KeyError:
      |         ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:292:9: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  292 |                 self.hide_window()
      |         ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:291:7: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  291 |             if not self.autocompletewindow.focus_get():
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:290:7: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  290 |         try:
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:289:7: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  289 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:288:7: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  288 |             return
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:287:7: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
  287 |         if not self.autocompletewindow:
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:286:7: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  286 |     def _hide_event_check(self):
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete_w.py:285:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
... (3073 more lines)
```

Exit code: 1
Elapsed: 10.24s
