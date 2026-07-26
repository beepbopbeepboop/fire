# COMPILE_FAIL: Lib/tkinter/simpledialog.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py: In function '_alloc__QueryFloat':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:221:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  221 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py: In function '_alloc__QueryInteger':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:235:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  235 |     minwidth = w.winfo_reqwidth()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py: In function '_alloc__QueryString':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:249:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  249 |             # Avoid the native menu bar which sits on top of everything.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py: In function 'SimpleDialog___init__':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:53:14: error: 'SimpleDialog' has no member named 'return_event'
   53 |         self.root.bind('<Return>', self.return_event)
      |              ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:61:14: error: 'SimpleDialog' has no member named 'wm_delete_window'
   61 |         self.root.protocol('WM_DELETE_WINDOW', self.wm_delete_window)
      |              ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:63:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   63 |         _place_window(self.root, master)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:62:1: warning: label 'bb_13' defined but not used [-Wunused-label]
   62 |         self.root.transient(master)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:60:1: warning: label 'bb_12' defined but not used [-Wunused-label]
   60 |             b.pack(side=LEFT, fill=BOTH, expand=1)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:68:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   68 |         self.root.mainloop()
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:65:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   65 |     def go(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:61:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   61 |         self.root.protocol('WM_DELETE_WINDOW', self.wm_delete_window)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:45:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   45 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:47:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   47 |         self.message.pack(expand=1, fill=BOTH)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:42:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   42 |             self.root.iconname(title)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/simpledialog.py:40:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   40 |         if title:
      | ^   
... (2951 more lines)
```

Exit code: 1
Elapsed: 14.74s
