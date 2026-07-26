# COMPILE_FAIL: Lib/idlelib/idle_test/mock_tk.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:74:11: warning: unused variable '_tag' [-Wunused-variable]
   74 |         module.messagebox = Mbox
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:79:11: warning: unused variable '_tag' [-Wunused-variable]
   79 |     ---
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:84:11: warning: unused variable '_tag' [-Wunused-variable]
   84 |     askokcancel = Mbox_func()     # True or False
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:99:11: warning: unused variable '_tag' [-Wunused-variable]
   99 |     index of actual lines start at 1, as with Tk. The methods never see this.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:108:13: warning: unused variable '_tag' [-Wunused-variable]
  108 |         '''Initialize mock, non-gui, text-only Text widget.
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py: In function 'Event___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:26:13: error: 'Event' has no member named '__dict__'
   26 |         self.__dict__.update(kwds)
      |             ^~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:219:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  219 |     def delete(self, index1, index2=None):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:217:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  217 |             return ''.join(lines)
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:216:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  216 |             lines.append(self.data[endline][:endchar])
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:215:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  215 |                 lines.append(self.data[i])
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py: In function 'Var___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:35:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   35 |     def set(self, value):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:33:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   33 |         self.value = value
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:32:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   32 |         self.master = master
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/mock_tk.py:31:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   31 |     def __init__(self, master=None, value=None, name=None):
      |           ^~~
... (1121 more lines)
```

Exit code: 1
Elapsed: 11.45s
