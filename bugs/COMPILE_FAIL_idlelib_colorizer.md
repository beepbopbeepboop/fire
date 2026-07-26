# COMPILE_FAIL: Lib/idlelib/colorizer.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py: In function '_alloc_ColorDelegator':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:128:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  128 |         self.allow_colorizing = True
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py: In function 'any_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:14:13: error: invalid operands to binary % (have 'char *' and 'int64_t' {aka 'long long int'})
   14 |     return "(?P<%s>" % name + "|".join(alternates) + ")"
      |             ^
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:495:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py: In function 'make_pat':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:46:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   46 |                    if not name.startswith('_') and
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:227:7: warning: variable '_t195' set but not used [-Wunused-but-set-variable]
  227 |             if DEBUG: print("cancel scheduled recolorizer")
      |       ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:224:11: warning: variable '_t192' set but not used [-Wunused-but-set-variable]
  224 |         if self.after_id:
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:148:11: warning: variable '_t125' set but not used [-Wunused-but-set-variable]
  148 |             self.bind("<<toggle-auto-coloring>>", self.toggle_colorize_event)
      |           ^ ~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:141:10: warning: variable '_t118' set but not used [-Wunused-but-set-variable]
  141 |         If there is a delegate, also start the colorizing process.
      |          ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:131:11: warning: variable '_t109' set but not used [-Wunused-but-set-variable]
  131 | 
      |           ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:114:11: warning: variable '_t93' set but not used [-Wunused-but-set-variable]
  114 |         stop_colorizing: Boolean flag to end an active colorizing
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:96:11: warning: variable '_t75' set but not used [-Wunused-but-set-variable]
   96 |         selectforeground=select_colors['foreground'],
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:61:11: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
   61 |                                ]),
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:44:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
   44 |     )
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py: In function 'matched_named_groups_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:79:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   79 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:75:11: warning: variable 'k' set but not used [-Wunused-but-set-variable]
   75 | 
      |           ^
/Users/mrs/net/Python-3.14.6/Lib/idlelib/colorizer.py:68:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   68 | prog_group_name_to_tag = {
... (1703 more lines)
```

Exit code: 1
Elapsed: 11.19s
