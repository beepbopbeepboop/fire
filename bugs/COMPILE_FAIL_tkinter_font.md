# COMPILE_FAIL: Lib/tkinter/font.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py: In function '_alloc_Font':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:80:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   80 |             name = "font" + str(next(self.counter))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py: In function 'nametofont_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:23:3: error: too few arguments to function 'Font___init__'; expected 6, have 5
   23 |     return Font(name=name, exists=True, root=root)
      |   ^ ~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:235:6: note: declared here
  235 |     fb.config(weight=BOLD)
      |      ^~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:319:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py: In function 'Font__set':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:57:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   57 |     def _get(self, args):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:63:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   63 |     def _mkdict(self, args):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:65:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   65 |         for i in range(0, len(args), 2):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:61:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   61 |         return tuple(options)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:63:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   63 |     def _mkdict(self, args):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:61:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
   61 |         return tuple(options)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:60:10: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   60 |             options.append("-"+k)
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:59:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
   59 |         for k in args:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:58:14: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
   58 |         options = []
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:57:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
   57 |     def _get(self, args):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:56:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
   56 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/font.py:55:7: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
   55 |         return tuple(options)
      |       ^ ~~
... (1029 more lines)
```

Exit code: 1
Elapsed: 14.50s
