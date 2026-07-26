# COMPILE_FAIL: Lib/tkinter/filedialog.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py: In function '_alloc_Directory':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:136:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  136 |         self.top.grab_set()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py: In function '_alloc_LoadFileDialog':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:150:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  150 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py: In function '_alloc_Open':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:164:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  164 |         file = self.files.get('active')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py: In function '_alloc_SaveAs':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:178:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  178 |             self.master.bell()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py: In function '_alloc_SaveFileDialog':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:192:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  192 |         for name in subdirs:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py: In function 'FileDialog___init__':
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:73:14: error: 'FileDialog' has no member named 'ok_event'
   73 |         self.selection.bind('<Return>', self.ok_event)
      |              ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:77:14: error: 'FileDialog' has no member named 'filter_command'
   77 |         self.filter.bind('<Return>', self.filter_command)
      |              ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:89:14: error: 'FileDialog' has no member named 'files_select_event'
   89 |         self.files.bind('<ButtonRelease-1>', self.files_select_event)
      |              ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:90:14: error: 'FileDialog' has no member named 'files_double_event'
   90 |         self.files.bind('<Double-ButtonRelease-1>', self.files_double_event)
      |              ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:101:15: error: 'FileDialog' has no member named 'dirs_select_event'
  101 |         self.dirs.bind('<ButtonRelease-1>', self.dirs_select_event)
      |               ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:102:15: error: 'FileDialog' has no member named 'dirs_double_event'
  102 |         self.dirs.bind('<Double-ButtonRelease-1>', self.dirs_double_event)
      |               ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:117:15: error: 'FileDialog' has no member named 'cancel_command'
  117 |         self.top.protocol('WM_DELETE_WINDOW', self.cancel_command)
      |               ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:119:15: error: 'FileDialog' has no member named 'cancel_command'
  119 |         self.top.bind('<Alt-w>', self.cancel_command)
      |               ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:120:15: error: 'FileDialog' has no member named 'cancel_command'
  120 |         self.top.bind('<Alt-W>', self.cancel_command)
      |               ^~
/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py:62:1: warning: label 'bb_4' defined but not used [-Wunused-label]
... (5993 more lines)
```

Exit code: 1
Elapsed: 14.00s
