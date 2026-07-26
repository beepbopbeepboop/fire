# COMPILE_FAIL: Lib/idlelib/squeezer.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py: In function '_alloc_ExpandingButton':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:92:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   92 |     Each button is tied to a Squeezer instance, and it knows to update the
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py: In function 'count_lines_with_wrapping_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:353:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:350:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:344:11: warning: variable 'tabwidth' set but not used [-Wunused-but-set-variable]
  344 | 
      |           ^       
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:343:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  343 |     main('idlelib.idle_test.test_squeezer', verbosity=2, exit=False)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py: In function 'ExpandingButton___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:123:1: warning: label 'bb_7' defined but not used [-Wunused-label]
  123 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:121:1: warning: label 'bb_8' defined but not used [-Wunused-label]
  121 |         self.selection_handle(  # X windows only.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:122:1: warning: label 'bb_6' defined but not used [-Wunused-label]
  122 |             lambda offset, length: s[int(offset):int(offset) + int(length)])
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:106:1: warning: label 'bb_5' defined but not used [-Wunused-label]
  106 |         button_text = f"Squeezed text ({numoflines} {line_plurality})."
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:106:1: warning: label 'bb_4' defined but not used [-Wunused-label]
  106 |         button_text = f"Squeezed text ({numoflines} {line_plurality})."
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:106:1: warning: label 'bb_3' defined but not used [-Wunused-label]
  106 |         button_text = f"Squeezed text ({numoflines} {line_plurality})."
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:153:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  153 |                     "The squeezed output is very long: %d lines, %d chars.",
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:151:11: warning: variable '_t61' set but not used [-Wunused-but-set-variable]
  151 |                 title="Expand huge output?",
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:150:7: warning: variable '_t60' set but not used [-Wunused-but-set-variable]
  150 |             confirm = messagebox.askokcancel(
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:149:11: warning: variable '_t59' set but not used [-Wunused-but-set-variable]
  149 |         if self.is_dangerous:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:148:11: warning: variable '_t58' set but not used [-Wunused-but-set-variable]
  148 |             self.set_is_dangerous()
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/squeezer.py:147:10: warning: variable '_t57' set but not used [-Wunused-but-set-variable]
  147 |         if self.is_dangerous is None:
... (942 more lines)
```

Exit code: 1
Elapsed: 10.74s
