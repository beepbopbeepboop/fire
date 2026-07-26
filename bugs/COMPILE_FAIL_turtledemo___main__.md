# COMPILE_FAIL: Lib/turtledemo/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py: In function '_alloc_DemoWindow':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:99:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   99 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py: In function 'getExampleEntries':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:382:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  382 |             self.clearCanvas()
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:381:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  381 |         if self.exitflag:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py: In function 'DemoWindow___init__':
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:129:6: error: request for member '_root' in something not a structure or union
  129 |         self.root = root = turtle._root = Tk()
      |      ^
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:131:14: error: 'DemoWindow' has no member named '_destroy'
  131 |         root.wm_protocol("WM_DELETE_WINDOW", self._destroy)
      |              ^~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:201:1: warning: label 'bb_9' defined but not used [-Wunused-label]
  201 |         self.state = STARTUP
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:201:1: warning: label 'bb_8' defined but not used [-Wunused-label]
  201 |         self.state = STARTUP
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:189:1: warning: label 'bb_6' defined but not used [-Wunused-label]
  189 |         self.output_lbl.grid(row=1, column=0, sticky='news', padx=(0,5))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:180:1: warning: label 'bb_7' defined but not used [-Wunused-label]
  180 |             self.start_btn = Button(root, text=" START ", font=btnfont,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:173:1: warning: label 'bb_5' defined but not used [-Wunused-label]
  173 |             self.start_btn = Button(root, text=" START ", font=btnfont,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:140:1: warning: label 'bb_4' defined but not used [-Wunused-label]
  140 |                         '-e', 'tell application "System Events"',
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:135:1: warning: label 'bb_3' defined but not used [-Wunused-label]
  135 |             # Make sure we are the currently activated OS X application
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:242:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  242 |         # calling Screen and manually call superclass init after.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:240:11: warning: variable '_t117' set but not used [-Wunused-but-set-variable]
  240 |         # by calling Screen.  Since tdemo canvas needs a different
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:239:7: warning: variable '_t116' set but not used [-Wunused-but-set-variable]
  239 |         # t._Screen is a singleton class instantiated or retrieved
      |       ^ ~~~
/Users/mrs/net/Python-3.14.6/Lib/turtledemo/__main__.py:238:7: warning: variable '_t115' set but not used [-Wunused-but-set-variable]
... (2064 more lines)
```

Exit code: 1
Elapsed: 22.34s
