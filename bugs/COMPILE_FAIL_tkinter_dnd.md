# COMPILE_FAIL: Lib/tkinter/dnd.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py: In function '_alloc_DndHandler':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:58:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   58 | None.  The new target object's method dnd_enter(source, event) is
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py: In function '_alloc_Icon':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:72:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   72 | mechanisms take over.
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py: In function '_alloc_Tester':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:86:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   86 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py: In function 'DndHandler___init__':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:139:14: error: 'DndHandler' has no member named 'on_release'
  139 |         widget.bind(self.release_pattern, self.on_release)
      |              ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:140:14: error: 'DndHandler' has no member named 'on_motion'
  140 |         widget.bind("<Motion>", self.on_motion)
      |              ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:139:1: warning: label 'bb_13' defined but not used [-Wunused-label]
  139 |         widget.bind(self.release_pattern, self.on_release)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:139:1: warning: label 'bb_12' defined but not used [-Wunused-label]
  139 |         widget.bind(self.release_pattern, self.on_release)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:139:1: warning: label 'bb_11' defined but not used [-Wunused-label]
  139 |         widget.bind(self.release_pattern, self.on_release)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:138:1: warning: label 'bb_7' defined but not used [-Wunused-label]
  138 |         self.save_cursor = widget['cursor'] or ""
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:135:1: warning: label 'bb_10' defined but not used [-Wunused-label]
  135 |         self.initial_button = button = event.num
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:141:1: warning: label 'bb_9' defined but not used [-Wunused-label]
  141 |         widget['cursor'] = "hand2"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:135:1: warning: label 'bb_5' defined but not used [-Wunused-label]
  135 |         self.initial_button = button = event.num
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:131:1: warning: label 'bb_6' defined but not used [-Wunused-label]
  131 |             root.__dnd = self
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:128:1: warning: label 'bb_4' defined but not used [-Wunused-label]
  128 |             root.__dnd
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dnd.py:228:1: warning: label 'bb_3' defined but not used [-Wunused-label]
  228 |         label.bind("<ButtonPress>", self.press)
      | ^   
... (1636 more lines)
```

Exit code: 1
Elapsed: 13.92s
