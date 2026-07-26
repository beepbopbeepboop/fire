# COMPILE_FAIL: Lib/idlelib/codecontext.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:47:11: warning: unused variable '_tag' [-Wunused-variable]
   47 |     UPDATEINTERVAL = 100  # millisec
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 |         editwin is the Editor window for the context block.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:57:11: warning: unused variable '_tag' [-Wunused-variable]
   57 |         self.topvisible is the number of the top text line displayed.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |         self.cell00 = None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:81:13: warning: unused variable '_tag' [-Wunused-variable]
   81 |                                                "maxlines", type="int",
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py: In function 'get_spaces_firstword_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:217:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  217 |         self.context['state'] = 'disabled'
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:215:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  215 |         self.context.delete('1.0', 'end')
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py: In function 'get_line_info_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:40:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   40 |         indent = INFINITY
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:36:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   36 |     """
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:33:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   33 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py: In function 'CodeContext___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:55:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   55 |         self.context displays the code context text above the editor text.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:53:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   53 |         self.text is the editor window text widget.
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:52:7: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   52 |         editwin is the Editor window for the context block.
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/codecontext.py:51:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   51 | 
... (1106 more lines)
```

Exit code: 1
Elapsed: 10.99s
