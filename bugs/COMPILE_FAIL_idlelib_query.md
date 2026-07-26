# COMPILE_FAIL: Lib/idlelib/query.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:345:11: warning: unused variable '_tag' [-Wunused-variable]
  345 |         """cli_args is a list of strings.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:350:11: warning: unused variable '_tag' [-Wunused-variable]
  350 |         message = 'Command Line Arguments for sys.argv:'
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:355:11: warning: unused variable '_tag' [-Wunused-variable]
  355 |     def create_extra(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:370:11: warning: unused variable '_tag' [-Wunused-variable]
  370 |         cli_string = self.entry.get().strip()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:379:13: warning: unused variable '_tag' [-Wunused-variable]
  379 |         "Return apparently valid (cli_args, restart) or None."
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py: In function 'Query___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:90:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   90 |         """Create entry (rows, extras, buttons.
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:87:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   87 |             self.wait_window()
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:75:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   75 |                 "+%d+%d" % (
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:75:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   75 |                 "+%d+%d" % (
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:75:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   75 |                 "+%d+%d" % (
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:69:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   69 |         self.bind('<Key-Return>', self.ok)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:74:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   74 |         self.geometry(  # Center dialog over parent (or below htest box).
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:65:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   65 |         if self._windowingsystem == 'aqua':
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:65:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   65 |         if self._windowingsystem == 'aqua':
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/query.py:629:1: warning: label 'bb_2' defined but not used [-Wunused-label]
... (3531 more lines)
```

Exit code: 1
Elapsed: 10.15s
