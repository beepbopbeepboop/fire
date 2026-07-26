# COMPILE_FAIL: Lib/idlelib/autocomplete.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete.py`

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
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete.py: In function 'AutoComplete___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete.py:46:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   46 |         # id of delayed call, and the index of the text insert when
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete.py:47:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   47 |         # the delayed call was issued. If _delayed_completion_id is
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:177:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:175:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:174:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:173:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:172:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:171:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:170:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:169:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:168:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:167:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:166:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:165:9: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/__main__.py:164:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete.py: In function 'AutoComplete_reload':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete.py:68:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   68 |         return "break"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete.py:66:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   66 |         "(^space) Open completion list, even if a function call is needed."
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete.py:65:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   65 |     def force_open_completions_event(self, event):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete.py:64:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   64 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autocomplete.py:63:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   63 |             self.autocompletewindow = None
      |          ^  
... (1106 more lines)
```

Exit code: 1
Elapsed: 9.75s
