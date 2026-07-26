# COMPILE_FAIL: Lib/idlelib/iomenu.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:97:11: warning: unused variable '_tag' [-Wunused-variable]
   97 |                         self.get_saved()):
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:102:11: warning: unused variable '_tag' [-Wunused-variable]
  102 |                 if self.text:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:107:11: warning: unused variable '_tag' [-Wunused-variable]
  107 |         if self.get_saved():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:122:11: warning: unused variable '_tag' [-Wunused-variable]
  122 |     eol_convention = os.linesep  # default
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:131:13: warning: unused variable '_tag' [-Wunused-variable]
  131 |                     file_timestamp = self.getmtime(filename)
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py: In function 'IOBinding___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:343:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  343 |             (tfd, tempfilename) = tempfile.mkstemp(prefix='IDLE_tmp_')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:341:7: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
  341 |         # shell undo is reset after every prompt, looks saved, probably isn't
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:340:7: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
  340 |             filename = self.filename
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:339:7: warning: variable '_t47' set but not used [-Wunused-but-set-variable]
  339 |         if saved:
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:338:11: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
  338 |         saved = self.get_saved()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:337:10: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
  337 |         tempfilename = None
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:336:7: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
  336 |             return "break"
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:335:10: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
  335 |             self.text.focus_set()
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:334:7: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
  334 |         if not confirm:
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/iomenu.py:333:11: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
... (1796 more lines)
```

Exit code: 1
Elapsed: 11.07s
