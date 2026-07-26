# COMPILE_FAIL: Lib/tkinter/dialog.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py: In function '_alloc_Dialog':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:46:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   46 |     q = Button(None, {'text': 'Quit',
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py: In function 'Dialog___init__':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:24:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   24 |     def destroy(self): pass
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:35:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   35 |                       'default': 0,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:27:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   27 | def _test():
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:24:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   24 |     def destroy(self): pass
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:25:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   25 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:285:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:283:9: warning: variable '_t74' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:282:9: warning: variable '_t73' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:281:11: warning: variable '_t72' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:280:9: warning: variable '_t71' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:279:11: warning: variable '_t70' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:278:11: warning: variable '_t69' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:277:11: warning: variable '_t68' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:276:11: warning: variable '_t67' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:275:10: warning: variable '_t66' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:274:12: warning: variable '_t65' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:273:11: warning: variable '_t64' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:272:11: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:271:10: warning: unused variable '_t62' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:269:7: warning: variable '_t60' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:268:7: warning: variable '_t59' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:267:9: warning: variable '_t58' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:266:7: warning: variable '_t57' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:265:7: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:264:7: warning: variable '_t55' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:263:7: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:262:11: warning: variable '_t53' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:261:10: warning: variable '_t52' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:260:11: warning: variable '_t51' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:259:11: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:258:11: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:257:14: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:256:10: warning: variable '_t47' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:255:11: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
... (84 more lines)
```

Exit code: 1
Elapsed: 13.81s
