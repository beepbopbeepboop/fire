# COMPILE_FAIL: Lib/idlelib/help_about.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:136:11: warning: unused variable '_tag' [-Wunused-variable]
  136 |         self.readme = Button(idle_buttons, text='Readme', width=8,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:141:11: warning: unused variable '_tag' [-Wunused-variable]
  141 |                                 highlightbackground=self.bg,
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:146:11: warning: unused variable '_tag' [-Wunused-variable]
  146 |                                    command=self.show_idle_credits)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:161:11: warning: unused variable '_tag' [-Wunused-variable]
  161 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:170:13: warning: unused variable '_tag' [-Wunused-variable]
  170 |         self.display_file_text('About - Readme', 'README.txt', 'ascii')
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py: In function 'AboutDialog___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:61:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   61 |         frame = Frame(self, borderwidth=2, relief=SUNKEN)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:59:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   59 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:45:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   45 |                    f'About IDLE {pyver} ({bits} bit)')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:45:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   45 |                    f'About IDLE {pyver} ({bits} bit)')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:45:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   45 |                    f'About IDLE {pyver} ({bits} bit)')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:38:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   38 |                         parent.winfo_rootx()+30,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:38:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   38 |                         parent.winfo_rootx()+30,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:38:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   38 |                         parent.winfo_rootx()+30,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:366:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:364:11: warning: variable '_t69' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:363:11: warning: variable '_t68' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/help_about.py:362:11: warning: variable '_t67' set but not used [-Wunused-but-set-variable]
... (895 more lines)
```

Exit code: 1
Elapsed: 12.03s
