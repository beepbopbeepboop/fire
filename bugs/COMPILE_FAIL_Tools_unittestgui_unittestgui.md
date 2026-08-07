# COMPILE_FAIL: Tools/unittestgui/unittestgui.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current error:

```
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:462:1: error: invalid types in conversion to integer
```

at `self.text = self.canvas.create_text(totalWidth/2, height/2,
anchor=tk.CENTER, text=percentString)` — a tkinter canvas call with a
`text=<char *>` KEYWORD argument. `self.text` (the struct field) is
declared `int` (plausible on its own — `create_text()` really does
return an integer tkinter widget/item ID in real Python), but the
`text=percentString` kwarg itself (a `char *` value going into what
this codegen presumably boxes as a generic kwargs dict expecting
`int64_t`-compatible values) is the more likely site of the actual
"invalid types in conversion to integer" — not conclusively pinned to
one specific line via the generated `.ci` (the `#line` directive
nearest the error is a different, coincidental `self->text = 0;`
default-init a few statements earlier, not the real call). Not
root-caused further; not fixed.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py: In function '_alloc_DiscoverSettingsDialog':
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:116:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  116 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py: In function '_alloc_GUITestResult':
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:130:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  130 |         "Override to indicate that a test has just failed"
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py: In function '_alloc_ProgressBar':
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:144:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  144 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py: In function '_alloc_RollbackImporter':
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:158:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  158 |     """
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py: In function '_alloc_TkTestRunner':
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:172:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  172 |         super(GUITestResult,self).addSkip(test, reason)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py: In function 'BaseGUITestRunner___init__':
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:610:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:608:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:607:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:606:10: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:605:7: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:604:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:603:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:602:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:601:7: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:600:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:599:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:598:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:597:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:596:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:595:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:594:22: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:593:22: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:592:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:591:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py: In function 'BaseGUITestRunner_errorDialog':
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:72:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   72 |         "Override to prompt user for directory to perform test discovery"
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:70:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   70 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py: In function 'BaseGUITestRunner_getDirectoryToDiscover':
/Users/mrs/net/Python-3.14.6/Tools/unittestgui/unittestgui.py:75:1: warning: label 'bb_2' defined but not used [-Wunused-label]
... (3378 more lines)
```

Exit code: 1
Elapsed: 11.62s
