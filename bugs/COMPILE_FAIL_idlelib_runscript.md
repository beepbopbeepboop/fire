# COMPILE_FAIL: Lib/idlelib/runscript.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:53:11: warning: unused variable '_tag' [-Wunused-variable]
   53 |         if not filename:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:58:11: warning: unused variable '_tag' [-Wunused-variable]
   58 |             return 'break'
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:63:11: warning: unused variable '_tag' [-Wunused-variable]
   63 |         with tokenize.open(filename) as f:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:78:11: warning: unused variable '_tag' [-Wunused-variable]
   78 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:87:13: warning: unused variable '_tag' [-Wunused-variable]
   87 |             source = source.replace(b'\r', b'\n')
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py: In function 'ScriptBinding___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:215:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:213:7: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  213 |     main('idlelib.idle_test.test_runscript', verbosity=2,)
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:212:14: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  212 |     from unittest import main
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:211:14: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  211 | if __name__ == "__main__":
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:210:7: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  210 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:209:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  209 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:208:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  208 |         self.perf = time.perf_counter()
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:207:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  207 |         self.editwin.text.focus_set()
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:206:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  206 |         messagebox.showerror(title, message, parent=self.editwin.text)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/runscript.py:205:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  205 |         # XXX This should really be a function of EditorWindow...
      |       ^ ~
... (1107 more lines)
```

Exit code: 1
Elapsed: 10.39s
