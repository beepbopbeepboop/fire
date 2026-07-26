# COMPILE_FAIL: Lib/idlelib/undo.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py: In function '_alloc_CommandSequence':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:117:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  117 |         if execute:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py: In function '_alloc_DeleteCommand':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:131:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  131 |             ##print "truncating undo list"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py: In function '_alloc_InsertCommand':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:145:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  145 |         self.pointer = self.pointer - 1
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py: In function '_alloc_UndoDelegator':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:159:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  159 |         return "break"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py: In function 'UndoDelegator___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:595:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:593:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:592:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:591:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:590:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:589:19: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:588:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:587:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py: In function 'UndoDelegator_setdelegate':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:41:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   41 |         from pprint import pprint
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:40:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   40 |     def dump_event(self, event):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:36:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   36 |             self.bind("<<undo>>", self.undo_event)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:64:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   64 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:59:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   59 |             self.saved = self.pointer
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:57:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
   57 |     def set_saved(self, flag):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:56:7: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
   56 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/undo.py:55:10: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
   55 |         self.set_saved(1)
... (2427 more lines)
```

Exit code: 1
Elapsed: 10.39s
