# COMPILE_FAIL: Lib/idlelib/multicall.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:152:11: warning: unused variable '_tag' [-Wunused-variable]
  152 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:157:11: warning: unused variable '_tag' [-Wunused-variable]
  157 |     # a detail (or None) and a state into a list of functions.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:162:11: warning: unused variable '_tag' [-Wunused-variable]
  162 |         def handler(event, lists = lists,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:177:11: warning: unused variable '_tag' [-Wunused-variable]
  177 |                         if r:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:186:13: warning: unused variable '_tag' [-Wunused-variable]
  186 |             if r:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py: In function '_SimpleBinder___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:382:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  382 |                 return
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:380:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
  380 |         def event_delete(self, virtual, *sequences):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:379:14: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
  379 | 
      |              ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:378:14: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  378 |                     triplets.append(triplet)
      |              ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:377:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  377 |                         self.__binders[triplet[1]].bind(triplet, func)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:376:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  376 |                     if func is not None:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:375:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  375 |                 else:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:374:10: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  374 |                     widget.event_add(self, virtual, seq)
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:373:7: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  373 |                     #print("Tkinter event_add(%s)" % seq, file=sys.__stderr__)
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/multicall.py:372:10: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
... (1215 more lines)
```

Exit code: 1
Elapsed: 11.00s
