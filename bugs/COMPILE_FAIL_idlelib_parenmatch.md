# COMPILE_FAIL: Lib/idlelib/parenmatch.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:53:11: warning: unused variable '_tag' [-Wunused-variable]
   53 |         cls.STYLE = idleConf.GetOption(
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:58:11: warning: unused variable '_tag' [-Wunused-variable]
   58 |                 'extensions','ParenMatch','bell', type='bool', default=1)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:63:11: warning: unused variable '_tag' [-Wunused-variable]
   63 |         "Activate mechanism to restore text from highlighting."
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:78:11: warning: unused variable '_tag' [-Wunused-variable]
   78 |         indices = (HyperParser(self.editwin, "insert")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:87:13: warning: unused variable '_tag' [-Wunused-variable]
   87 |         if closer not in _openers:
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py: In function 'ParenMatch___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:217:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:215:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:214:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:213:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:212:7: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:211:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:210:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:209:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:208:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:207:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:206:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:205:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:204:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:203:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:202:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py: In function 'ParenMatch_reload':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:100:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  100 |         self.activate_restore()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:98:10: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
   98 |             self.text.bell()
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:97:11: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
   97 |         if indices is None and self.BELL:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/parenmatch.py:96:11: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
   96 |     def finish_paren_event(self, indices):
      |           ^~~~
... (1015 more lines)
```

Exit code: 1
Elapsed: 10.82s
